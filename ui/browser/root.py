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

from ...imgs import MAIN_ICON
from ...pyqt_version import exec_dialog
from ...settings_manager import get_settings
from ...strato import api, constants
from ...ui.dialog_account import DialogAccount
from ...ui.dialog_login import DialogLogin
from ...ui.dialog_project_select import ProjectSelectDialog
from .styledmap import StyledMapRoot
from .vector import DbRoot


class DataItemProvider(QgsDataItemProvider):
    """Provider for STRATO browser items"""

    def __init__(self):
        QgsDataItemProvider.__init__(self)

    def name(self):
        return constants.PLUGIN_NAME

    def capabilities(self):
        return QgsDataProvider.Net

    def createDataItem(self, path, parent):
        return RootCollection()


class RootCollection(QgsDataCollectionItem):
    """Root collection for STRATO browser"""

    def __init__(self):
        # Initialize with default name, will update with project name later
        QgsDataCollectionItem.__init__(
            self, None, constants.PLUGIN_NAME, constants.BROWSER_ROOT_PATH
        )
        self.setIcon(MAIN_ICON)

        self.setName(constants.PLUGIN_NAME)

        self.organization_data = None
        self.project_data = None

        self.project_select_dialog = None

        self.load_organization_project()

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
        try:
            self.organization_data = api.organization.get_organization(
                settings.selected_organization_id
            )
            self.project_data = api.project.get_project(settings.selected_project_id)
            self.setName(
                f"{constants.PLUGIN_NAME}: {self.project_data.name}({self.organization_data.name})"
            )
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error reloading organization/project data: {str(e)}",
                constants.LOG_CATEGORY,
                Qgis.Warning,
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

        return [select_project_action, refresh_action, account_action]

    def refreshChildren(self):
        """Refresh the children of the root collection"""
        self.load_organization_project()
        self.refresh()
        self.depopulate()

    def login(self):
        """Login to STRATO"""

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
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return

        prev_project_id = get_settings().selected_project_id

        # プロジェクト選択ダイアログは初回時のみ生成、それ以降は再利用する
        if self.project_select_dialog is None:
            self.project_select_dialog = ProjectSelectDialog()
        else:
            self.project_select_dialog.load_user_info()
            self.project_select_dialog.load_organizations()
            self.project_select_dialog.load_saved_selection()
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
        dialog = DialogAccount()
        should_logout = exec_dialog(dialog)

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
            return children

        vector_path = f"{self.path()}/vectors"
        vector_root = DbRoot(
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
