from qgis.core import (
    Qgis,
    QgsDataCollectionItem,
    QgsDataItemProvider,
    QgsDataProvider,
    QgsMessageLog,
    QgsProject,
)
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.utils import iface

from ...pyqt_version import exec_dialog, Q_MESSAGEBOX_STD_BUTTON
from ...settings_manager import get_settings, store_setting
from ...kumoy import api, constants
from ...kumoy.api.error import format_api_error
from ...ui.dialog_account import DialogAccount
from ...ui.dialog_login import DialogLogin
from ...ui.dialog_project_select import ProjectSelectDialog
from ..darkmode import get_adaptive_icon
from .styledmap import StyledMapRoot
from .utils import ErrorItem, is_in_darkmode
from .vector import VectorRoot


class DataItemProvider(QgsDataItemProvider):
    """Provider for KUMOY browser items"""

    def __init__(self):
        QgsDataItemProvider.__init__(self)

    def name(self):
        return constants.PLUGIN_NAME

    def capabilities(self):
        return QgsDataProvider.Net

    def createDataItem(self, path, parent):
        return RootCollection()


class RootCollection(QgsDataCollectionItem):
    """Root collection for KUMOY browser"""

    def __init__(self):
        # Initialize with default name, will update with project name later
        QgsDataCollectionItem.__init__(
            self, None, constants.PLUGIN_NAME, constants.BROWSER_ROOT_PATH
        )
        self.setIcon(get_adaptive_icon())

        self.setName(constants.PLUGIN_NAME)

        self.organization_data = None
        self.project_data = None

        self.project_select_dialog = None
        self.account_setting_dialog = None

        try:
            self.load_organization_project()
        except Exception as e:
            msg = self.tr("Error loading organization/project data: {}").format(
                format_api_error(e)
            )
            QgsMessageLog.logMessage(msg, constants.LOG_CATEGORY, Qgis.Warning)

    def load_organization_project(self):
        self.organization_data = None
        self.project_data = None

        settings = get_settings()
        if (
            settings.id_token == ""
            or settings.selected_organization_id == ""
            or settings.selected_project_id == ""
        ):
            return

        # Get organization and project details
        self.organization_data = api.organization.get_organization(
            settings.selected_organization_id
        )
        self.project_data = api.project.get_project(settings.selected_project_id)
        self.setName(
            f"{constants.PLUGIN_NAME}: {self.project_data.name}({self.organization_data.name})"
        )

    def tr(self, message):
        """Get the translation for a string using Qt translation API"""
        return QCoreApplication.translate("RootCollection", message)

    def handleDoubleClick(self):
        # 非ログイン時ならログイン画面を開く
        if not get_settings().id_token:
            self.login()

        return False  # デフォルトのダブルクリック動作を実行

    def actions(self, parent):
        id_token = get_settings().id_token
        if not id_token:
            # Login action
            login_action = QAction(self.tr("Login"), parent)
            login_action.triggered.connect(self.login)
            return [login_action]

        # Select Project action
        select_project_action = QAction(self.tr("Select Project"), parent)
        select_project_action.triggered.connect(self.select_project)

        # Refresh action
        refresh_action = QAction(self.tr("Refresh"), parent)
        refresh_action.triggered.connect(self.refreshChildren)

        # Account action
        account_action = QAction(self.tr("Account"), parent)
        account_action.triggered.connect(self.account_settings)

        # Logout action
        logout_action = QAction(self.tr("Logout"), parent)
        logout_action.triggered.connect(self.logout)

        return [select_project_action, refresh_action, account_action, logout_action]

    def refreshChildren(self):
        """Refresh the children of the root collection"""
        try:
            self.load_organization_project()
        except Exception as e:
            msg = self.tr("Error loading organization/project data: {}").format(
                format_api_error(e)
            )
            QgsMessageLog.logMessage(msg, constants.LOG_CATEGORY, Qgis.Warning)
            QMessageBox.critical(None, self.tr("Error"), msg)

        self.refresh()
        self.depopulate()

    def login(self):
        """Login to KUMOY"""

        # Show config dialog with Supabase login tab
        dialog = DialogLogin()
        result = exec_dialog(dialog)

        if result:
            self.select_project()

    def select_project(self):
        """Select a project to display"""
        # Warn if current project has unsaved changes
        if QgsProject.instance().isDirty() and (
            QMessageBox.question(
                None,
                self.tr("Change Project"),
                self.tr(
                    "Switching projects will discard the current map state. Continue?"
                ),
                Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
                Q_MESSAGEBOX_STD_BUTTON.No,
            )
            != Q_MESSAGEBOX_STD_BUTTON.Yes
        ):
            return

        prev_project_id = get_settings().selected_project_id

        # プロジェクト選択ダイアログは初回時のみ生成、それ以降は再利用する
        try:
            if self.project_select_dialog is None:
                self.project_select_dialog = ProjectSelectDialog()
            else:
                self.project_select_dialog.load_user_info()
                self.project_select_dialog.load_organizations()
                self.project_select_dialog.load_saved_selection()
        except Exception as e:
            msg = self.tr("Error loading project selection dialog: {}").format(
                format_api_error(e)
            )
            QgsMessageLog.logMessage(msg, constants.LOG_CATEGORY, Qgis.Warning)
            QMessageBox.critical(None, self.tr("Error"), msg)
            return

        result = exec_dialog(self.project_select_dialog)

        if not result:
            return

        # 同一のProjectを選択していない場合はプロジェクトをクリアする
        if prev_project_id != get_settings().selected_project_id:
            QgsProject.instance().clear()
            iface.messageBar().pushSuccess(
                self.tr("Project Changed"),
                self.tr(
                    "Your QGIS project was cleared because the active project changed."
                ),
            )
            self.refreshChildren()

    def account_settings(self):
        """Show account settings dialog"""
        try:
            if self.account_setting_dialog is None:
                self.account_setting_dialog = DialogAccount()
            else:
                self.account_setting_dialog._load_user_info()
                self.account_setting_dialog._load_server_config()
        except Exception as e:
            msg = self.tr("Error loading account settings dialog: {}").format(
                format_api_error(e)
            )
            QgsMessageLog.logMessage(msg, constants.LOG_CATEGORY, Qgis.Warning)
            QMessageBox.critical(None, self.tr("Error"), msg)
            return

        should_logout = exec_dialog(self.account_setting_dialog)

        if should_logout:
            # Reset browser name
            self.organization_data = None
            self.project_data = None
            self.setName(constants.PLUGIN_NAME)
            # Refresh to update UI
            self.refreshChildren()

    def createChildren(self):
        """Create child items for the root collection"""
        # Create vector root directly
        children = []

        if self.organization_data is None or self.project_data is None:
            return [
                ErrorItem(
                    self,
                    self.tr("Please select a project"),
                )
            ]

        vector_path = f"{self.path()}/vectors"
        vector_root = VectorRoot(
            self,
            "Vectors",
            vector_path,
            self.organization_data,
            self.project_data,
        )
        children.append(vector_root)

        # Create styled map root
        styled_map_path = f"{self.path()}/styledmaps"
        styled_map_root = StyledMapRoot(
            self, "Maps", styled_map_path, self.organization_data, self.project_data
        )
        children.append(styled_map_root)

        return children

    def logout(self):
        """Logout from KUMOY"""
        if QgsProject.instance().isDirty():
            confirmed = QMessageBox.question(
                None,
                self.tr("Logout"),
                self.tr(
                    "You have unsaved changes. "
                    "Logging out will clear your current project. Continue?"
                ),
                Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
                Q_MESSAGEBOX_STD_BUTTON.No,
            )

            if confirmed != Q_MESSAGEBOX_STD_BUTTON.Yes:
                return

        QgsProject.instance().clear()

        # Clear stored settings
        store_setting("id_token", "")
        store_setting("refresh_token", "")
        store_setting("user_info", "")
        store_setting("selected_project_id", "")
        store_setting("selected_organization_id", "")

        QgsMessageLog.logMessage(
            "Logged out via browser root", constants.LOG_CATEGORY, Qgis.Info
        )
        QMessageBox.information(
            None,
            self.tr("Logout"),
            self.tr("You have been logged out from KUMOY."),
        )

        # Reset browser name
        self.setName(constants.PLUGIN_NAME)
        self.refreshChildren()
