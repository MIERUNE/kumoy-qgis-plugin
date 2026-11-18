"""Session lifecycle shared by the plugin menu, the Browser and dialogs:
startup, version check, logout and settings reset."""

from typing import Callable, Optional

from qgis.core import Qgis, QgsMessageLog, QgsProject, QgsVectorLayer
from qgis.PyQt.QtWidgets import QWidget
from qgis.utils import iface

from .. import i18n
from ..kumoy import api, constants, session, settings_manager
from ..kumoy.api.error import format_api_error
from ..kumoy.tasks import run_task
from ..plugin_version import is_plugin_version_compatible, read_plugin_version
from ..processing.close_all_processing_dialogs import close_all_processing_dialogs
from .error_handler import (
    describe_error,
    end_session,
    push_success,
    refresh_kumoy_browser,
)
from .utils import confirm, kumoy_map_open


def start_session() -> None:
    """Load the stored login once QGIS has started.

    Deferred from initGui because unlocking the token may ask for the QGIS
    master password: a prompt during plugin loading would block startup (and
    appear behind the splash screen). It is done once, right after startup,
    rather than on the first Kumoy interaction because most entry points
    (Browser population, Processing, data providers) run on worker threads
    that cannot prompt.
    """
    session.load()
    if session.is_logged_in():
        check_plugin_version()
    refresh_kumoy_browser()


def check_plugin_version() -> None:
    """Log out in the background if the server requires a newer plugin."""
    if not session.is_logged_in():
        return

    def on_success(params: api.models.PublicParams) -> None:
        minimum = params.minQgisPluginVersion
        if minimum is None or is_plugin_version_compatible(
            read_plugin_version(), minimum
        ):
            return
        QgsMessageLog.logMessage(
            "Logged out due to incompatible plugin version",
            constants.LOG_CATEGORY,
            Qgis.Warning,
        )
        logout(ask=False)
        if iface is not None:
            iface.messageBar().pushMessage(
                i18n.tr("Plugin Version Error"),
                i18n.tr(
                    "Please update the Kumoy plugin. Minimum required version: {}"
                ).format(minimum),
                Qgis.Critical,
                0,
            )

    def on_error(e: Exception) -> None:
        # Not fatal: the next API call reports its own error if the server is
        # really unreachable, so do not interrupt the user with a dialog
        QgsMessageLog.logMessage(
            f"Version check failed: {format_api_error(e)}",
            constants.LOG_CATEGORY,
            Qgis.Warning,
        )
        if iface is not None:
            iface.messageBar().pushMessage(
                i18n.tr("Kumoy"), describe_error(e), Qgis.Warning, 10
            )

    run_task(
        i18n.tr("Checking Kumoy plugin version"),
        lambda task: api.user.get_public_params(),
        on_success,
        on_error,
    )


def _has_unsaved_kumoy_edits() -> bool:
    return any(
        isinstance(layer, QgsVectorLayer)
        and layer.providerType() == constants.DATA_PROVIDER_KEY
        and layer.isModified()
        for layer in QgsProject.instance().mapLayers().values()
    )


def _closing_map_note() -> str:
    """Sentence about what happens to the open project, or ""."""
    if kumoy_map_open():
        if QgsProject.instance().isDirty() or _has_unsaved_kumoy_edits():
            return i18n.tr(
                "The open Kumoy map will be closed and its unsaved changes lost."
            )
        return i18n.tr("The open Kumoy map will be closed.")
    if _has_unsaved_kumoy_edits():
        return i18n.tr(
            "Some Kumoy layers have unsaved edits, which cannot be saved after "
            "logging out."
        )
    return ""


def _sign_out(clear_project: bool, then: Callable[[], None] = lambda: None) -> None:
    """End the session; `then` runs once the server sign-out request is done
    (it reads the server URL from the settings, so they must outlive it)."""
    token = session.get_token()
    refresh_token = session.get_refresh_token()
    if token:

        def on_error(e: Exception) -> None:
            QgsMessageLog.logMessage(
                f"Sign-out request failed: {format_api_error(e)}",
                constants.LOG_CATEGORY,
                Qgis.Info,
            )
            then()

        # Revoke the login on the server so a copied token stops working. Failing
        # (e.g. offline) must not keep the user logged in locally.
        run_task(
            i18n.tr("Kumoy logout"),
            lambda task: api.auth.sign_out(token, refresh_token),
            lambda _: then(),
            on_error,
        )
    else:
        then()
    end_session()
    settings_manager.clear_selection()
    close_all_processing_dialogs()
    if clear_project:
        QgsProject.instance().clear()
    refresh_kumoy_browser()


def logout(parent: Optional[QWidget] = None, ask: bool = True) -> bool:
    """Log out of Kumoy. Returns False when the user canceled.

    With ask=False (forced logout) nothing is asked and the open project is
    kept, so no work is lost without the user agreeing to it.
    """
    note = _closing_map_note() if ask else ""
    if note and not confirm(
        parent, i18n.tr("Logout"), note + "\n\n" + i18n.tr("Continue?")
    ):
        return False
    _sign_out(clear_project=ask and kumoy_map_open())
    if ask:
        push_success(i18n.tr("You have been logged out from Kumoy."))
    return True


def reset_settings(parent: Optional[QWidget] = None) -> None:
    text = i18n.tr(
        'Are you sure you want to reset all settings for the "Kumoy" plugin? '
        "You will be logged out."
    )
    note = _closing_map_note()
    if note:
        text += "\n\n" + note
    if not confirm(parent, i18n.tr("Reset Plugin Settings"), text):
        return
    _sign_out(clear_project=kumoy_map_open(), then=settings_manager.reset)
    push_success(i18n.tr("Plugin settings have been reset successfully."))
