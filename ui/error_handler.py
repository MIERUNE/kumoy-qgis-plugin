"""Report API errors to the user, and end the session on 401.

Usable from any thread: the UI part is dispatched to the main thread.
"""

from typing import Callable, Optional

from qgis.core import Qgis, QgsApplication, QgsMessageLog
from qgis.PyQt.QtCore import QObject, QThread, pyqtSignal
from qgis.PyQt.QtWidgets import QMessageBox, QWidget
from qgis.utils import iface

from .. import i18n
from ..kumoy import constants, session
from ..kumoy.api import client
from ..kumoy.api.error import (
    ForbiddenError,
    NetworkError,
    QuotaExceededError,
    UnauthorizedError,
    UnderMaintenanceError,
    format_api_error,
)
from ..kumoy.basemap import remove_xyz_connections
from ..kumoy.tasks import Canceled


class _MainThreadDispatcher(QObject):
    call = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.call.connect(lambda fn: fn())


_dispatcher: Optional[_MainThreadDispatcher] = None


def run_on_main_thread(fn: Callable[[], None]) -> None:
    """Run fn on the main thread: now if already there, else queued."""
    global _dispatcher
    app = QgsApplication.instance()
    if app is None or QThread.currentThread() == app.thread():
        fn()
        return
    if _dispatcher is None:
        # Created lazily but must live in the main thread to receive queued calls
        _dispatcher = _MainThreadDispatcher()
        _dispatcher.moveToThread(app.thread())
    _dispatcher.call.emit(fn)


def refresh_kumoy_browser() -> None:
    """Rebuild the Kumoy node in the Browser panel (via the public registry)."""
    registry = QgsApplication.instance().dataItemProviderRegistry()
    for provider in registry.providers():
        if provider.name() == constants.PLUGIN_NAME:
            root = getattr(provider, "root_collection", None)
            if root is not None:
                root.refresh()
            return


def end_session() -> None:
    """Forget the login locally (the server already rejected it, or logout)."""
    session.clear()
    remove_xyz_connections()
    if iface:
        iface.reloadConnections()


def _session_expired() -> None:
    # Several requests fail together when a session expires; notify once
    if not session.is_logged_in():
        return
    end_session()
    QgsMessageLog.logMessage(
        "Session expired. Cleared local session token.",
        constants.LOG_CATEGORY,
        Qgis.Warning,
    )
    refresh_kumoy_browser()
    if iface is None:
        return
    box = QMessageBox(iface.mainWindow())
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(i18n.tr("Session expired"))
    box.setText(
        i18n.tr(
            "Your Kumoy session has expired or was signed out. Please log in again."
        )
    )
    login = box.addButton(i18n.tr("Log In"), QMessageBox.ButtonRole.AcceptRole)
    box.addButton(i18n.tr("Later"), QMessageBox.ButtonRole.RejectRole)
    box.exec()
    if box.clickedButton() is login:
        from .dialog_login import open_login_dialog

        open_login_dialog()


def describe_error(exception: Exception) -> str:
    """User-facing explanation of an API error."""
    detail = format_api_error(exception)
    if isinstance(exception, ForbiddenError):
        return i18n.tr(
            "You do not have permission for this operation. Editing requires the "
            "Editor role in the project's team, and some features require a paid "
            "plan. Details: {}"
        ).format(detail)
    if isinstance(exception, QuotaExceededError):
        return i18n.tr(
            "Your organization has reached a limit of its plan. Details: {}"
        ).format(detail)
    if isinstance(exception, NetworkError):
        return i18n.tr(
            "Could not connect to Kumoy ({}). Check your internet connection and "
            "proxy settings. Details: {}"
        ).format(client.server_url(), detail)
    if isinstance(exception, UnderMaintenanceError):
        return i18n.tr("Kumoy is under maintenance. Please try again later.")
    return detail


def handle_api_error(
    exception: Exception,
    parent: Optional[QWidget] = None,
    title: str = "",
) -> None:
    """Report `exception`. 401 ends the session; cancellation is silent.

    Errors go to the message bar so they do not block work; pass `parent` to
    show a dialog instead when the error belongs to an open dialog.
    """
    if isinstance(exception, Canceled):
        return
    if isinstance(exception, UnauthorizedError):
        run_on_main_thread(_session_expired)
        return

    title = title or i18n.tr("Kumoy")
    message = describe_error(exception)
    QgsMessageLog.logMessage(
        f"{title}: {format_api_error(exception)}", constants.LOG_CATEGORY, Qgis.Warning
    )

    def show() -> None:
        if parent is not None:
            QMessageBox.critical(parent, title, message)
        elif iface is not None:
            iface.messageBar().pushMessage(title, message, Qgis.Critical, 0)

    run_on_main_thread(show)


def push_success(message: str, title: str = "") -> None:
    if iface is not None:
        iface.messageBar().pushMessage(
            title or i18n.tr("Kumoy"), message, Qgis.Success, 5
        )
