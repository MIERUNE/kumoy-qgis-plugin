from qgis.core import (
    QgsDataCollectionItem,
    QgsDataItemProvider,
    QgsDataProvider,
    QgsProject,
)
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.utils import iface

from ... import i18n
from ..error_handler import handle_api_error
from ...kumoy import api, constants
from ...pyqt_version import Q_MESSAGEBOX_STD_BUTTON, exec_dialog
from ...kumoy.settings_manager import get_settings
from ...ui.dialog_account import DialogAccount
from ...ui.dialog_login import DialogLogin
from ...ui.dialog_project_select import ProjectSelectDialog
from ...ui.icons import MAIN_ICON
from .styledmap import StyledMapRoot
from .utils import ErrorItem
from .vector import VectorRoot


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
    """Root collection for Kumoy browser"""

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
        self.account_setting_dialog = None

        try:
            self.load_organization_project()
        except Exception as e:
            handle_api_error(
                e,
                parent=None,
                log_prefix=i18n.tr("Error loading organization/project data"),
            )

    def load_organization_project(self):
        self.organization_data = None
        self.project_data = None
        # ログアウト/セッション切れ時にも呼ばれるので、まずプレーンな表示名へ戻す。
        self.setName(constants.PLUGIN_NAME)

        settings = get_settings()
        if (
            settings.session_token == ""
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

    def handleDoubleClick(self):
        # 非ログイン時ならログイン画面を開く
        if not get_settings().session_token:
            self.login()

        return False  # デフォルトのダブルクリック動作を実行

    def actions(self, parent):
        session_token = get_settings().session_token
        if not session_token:
            # Login action
            login_action = QAction(i18n.tr("Login"), parent)
            login_action.triggered.connect(self.login)
            return [login_action]

        # Select Project action
        select_project_action = QAction(i18n.tr("Select Project"), parent)
        select_project_action.triggered.connect(self.select_project)

        # Refresh action
        refresh_action = QAction(i18n.tr("Refresh"), parent)
        refresh_action.triggered.connect(self.refresh)

        # Account action
        account_action = QAction(i18n.tr("Account"), parent)
        account_action.triggered.connect(self.account_settings)

        return [select_project_action, refresh_action, account_action]

    def refresh(self):
        """Refresh the children of the root collection
        also called when refresh button is clicked in browser panel"""

        try:
            self.load_organization_project()
        except Exception as e:
            handle_api_error(
                e,
                parent=None,
                log_prefix=i18n.tr("Error loading organization/project data"),
            )

        self.depopulate()

    def login(self):
        """Login to Kumoy"""

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
                i18n.tr("Change Project"),
                i18n.tr(
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
            handle_api_error(
                e,
                parent=None,
                log_prefix=i18n.tr("Error loading project selection dialog"),
            )
            return

        result = exec_dialog(self.project_select_dialog)

        if not result:
            return

        # 別Projectを選んだ場合だけ QGIS Project をクリアする。
        # ただしブラウザ自体は常にリフレッシュする：セッション切れ→再ログインで
        # 同じプロジェクトを選び直したとき、selected_project_id が変わっていない
        # ので前者の条件だけだと「Please select a project」表示のまま残ってしまう。
        if prev_project_id != get_settings().selected_project_id:
            QgsProject.instance().clear()
            iface.messageBar().pushSuccess(
                i18n.tr("Project Changed"),
                i18n.tr(
                    "Your QGIS project was cleared because the active project changed."
                ),
            )
        self.refresh()

    def account_settings(self):
        """Show account settings dialog"""
        try:
            if self.account_setting_dialog is None:
                self.account_setting_dialog = DialogAccount()
            else:
                self.account_setting_dialog._load_user_info()
                self.account_setting_dialog._load_server_config()
        except Exception as e:
            handle_api_error(
                e,
                parent=None,
                log_prefix=i18n.tr("Error loading account settings dialog"),
            )
            return

        should_logout = exec_dialog(self.account_setting_dialog)

        if should_logout:
            # Reset browser name
            self.organization_data = None
            self.project_data = None
            self.setName(constants.PLUGIN_NAME)
            # Refresh to update UI
            self.refresh()

    def createChildren(self):
        """Create child items for the root collection"""
        # Create vector root directly
        children = []

        if self.organization_data is None or self.project_data is None:
            return [
                ErrorItem(
                    self,
                    i18n.tr("Please select a project"),
                )
            ]

        vector_path = f"{self.path()}/vectors"
        vector_root = VectorRoot(
            self,
            i18n.tr("Vectors"),
            vector_path,
            self.organization_data,
            self.project_data,
        )
        vector_root.setSortKey(1)
        children.append(vector_root)

        # Create styled map root
        styled_map_path = f"{self.path()}/styledmaps"
        styled_map_root = StyledMapRoot(
            self,
            i18n.tr("Maps"),
            styled_map_path,
            self.organization_data,
            self.project_data,
        )
        styled_map_root.setSortKey(0)
        children.append(styled_map_root)

        return children
