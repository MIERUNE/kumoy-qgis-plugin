from typing import List, Optional, Tuple

from qgis.core import (
    Qgis,
    QgsDataCollectionItem,
    QgsDataItem,
    QgsDataItemProvider,
    QgsDataProvider,
)
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QAction

from ... import i18n
from ...kumoy import api, constants, session, settings_manager
from ...kumoy.api.models import OrganizationDetail, ProjectDetail
from ...pyqt_version import exec_dialog
from ..dialog_account import DialogAccount
from ..dialog_login import open_login_dialog
from ..dialog_project_select import open_project_dialog
from ..error_handler import run_on_main_thread
from ..icons import MAIN_ICON
from .raster import RasterRoot
from .styledmap import StyledMapRoot
from .utils import ActionItem, error_item
from .vector import VectorRoot

# The selected project as last loaded by the Browser. Read by the layer
# context menu (plugin.py) to decide on "Convert to Kumoy ..." without a
# network call; None until loaded or when logged out.
_current: Optional[ProjectDetail] = None


def current_project() -> Optional[ProjectDetail]:
    """The selected project's details, if loaded and still selected."""
    if _current is None or _current.id != settings_manager.selected_project_id():
        return None
    return _current


class DataItemProvider(QgsDataItemProvider):
    """Provider for Kumoy browser items"""

    def __init__(self):
        QgsDataItemProvider.__init__(self)
        self.root_collection = RootCollection()

    def name(self):
        return constants.PLUGIN_NAME

    def capabilities(self):
        return QgsDataProvider.Net

    def createDataItem(self, path, parent):
        return self.root_collection


class RootCollection(QgsDataCollectionItem):
    """The "Kumoy" node. Never touches the network on the main thread: the
    organization and project are loaded in createChildren, which QGIS runs
    on a worker thread."""

    def __init__(self):
        QgsDataCollectionItem.__init__(
            self, None, constants.PLUGIN_NAME, constants.BROWSER_ROOT_PATH
        )
        self.setIcon(MAIN_ICON)
        self._refresh_pending = False

    def refresh(self):
        """Rebuild all children: they were made for one project and login."""
        if self.state() == Qgis.BrowserItemState.Populating:
            # Retry once the current load ends, or this change would be lost.
            # Polls because stateChanged's enum arg can't be converted by SIP.
            if not self._refresh_pending:
                self._refresh_pending = True
                QTimer.singleShot(200, self._retry_refresh)
            return
        self.depopulate()
        super().refresh()

    def _retry_refresh(self) -> None:
        self._refresh_pending = False
        try:
            self.refresh()
        except RuntimeError:
            pass  # the Browser deleted the item (plugin unloaded)

    def _set_title(self, title: str) -> None:
        # From the worker thread via run_on_main_thread
        try:
            if self.name() != title:
                self.setName(title)
                self.dataChanged.emit(self)
        except RuntimeError:
            pass  # the Browser deleted the item (plugin unloaded)

    def handleDoubleClick(self):
        if not session.is_logged_in():
            open_login_dialog()
            return True
        return False

    def actions(self, parent):
        if not session.is_logged_in():
            login_action = QAction(i18n.tr("Log In…"), parent)
            login_action.triggered.connect(open_login_dialog)
            return [login_action]

        select_project_action = QAction(i18n.tr("Select Project"), parent)
        select_project_action.triggered.connect(open_project_dialog)

        refresh_action = QAction(i18n.tr("Refresh"), parent)
        refresh_action.triggered.connect(self.refresh)

        account_action = QAction(i18n.tr("Account"), parent)
        account_action.triggered.connect(self.account_settings)

        return [select_project_action, refresh_action, account_action]

    def account_settings(self):
        exec_dialog(DialogAccount())

    def createChildren(self):
        # Worker thread: no widgets, no iface
        global _current
        _current = None
        title = constants.PLUGIN_NAME
        try:
            children, loaded = self._load_children()
            if loaded is not None:
                organization, _current = loaded
                title = f"{title}: {_current.name}({organization.name})"
            return children
        finally:
            run_on_main_thread(lambda: self._set_title(title))

    def _load_children(
        self,
    ) -> Tuple[List[QgsDataItem], Optional[Tuple[OrganizationDetail, ProjectDetail]]]:
        if not session.is_logged_in():
            login_item = ActionItem(
                self, i18n.tr("Log in…"), f"{self.path()}/login", open_login_dialog
            )
            return [login_item], None
        organization_id = settings_manager.selected_organization_id()
        project_id = settings_manager.selected_project_id()
        select_item = ActionItem(
            self,
            i18n.tr("Select project…"),
            f"{self.path()}/select",
            open_project_dialog,
        )
        if not organization_id or not project_id:
            return [select_item], None

        try:
            organization = api.organization.get_organization(organization_id)
            project = api.project.get_project(project_id)
        except Exception as e:
            # Also when the project was deleted or access was revoked: offer
            # to pick another one instead of a dead end
            error = error_item(self, i18n.tr("Could not load the project"), e)
            return [error, select_item], None

        path = f"{self.path()}{project.id}"
        children = [
            StyledMapRoot(
                self, i18n.tr("Maps"), f"{path}/styledmaps", organization, project
            ),
            VectorRoot(
                self, i18n.tr("Vectors"), f"{path}/vectors", organization, project
            ),
            RasterRoot(
                self, i18n.tr("Rasters"), f"{path}/rasters", organization, project
            ),
        ]
        for key, child in enumerate(children):
            child.setSortKey(key)
        return children, (organization, project)
