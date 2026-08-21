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
from ...kumoy.settings_manager import get_settings, store_setting
from ...ui.dialog_account import DialogAccount
from ...ui.dialog_login import DialogLogin
from ...ui.dialog_organization_select import OrganizationSelectDialog
from ...ui.dialog_project_select import ProjectSelectDialog
from ...ui.icons import MAIN_ICON
from .catalog import CatalogRoot
from .project import ProjectRoot
from .utils import ErrorItem


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

        self.organization_select_dialog = None
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
            not settings.session_token
            or not settings.selected_organization_id
            or not settings.selected_project_id
        ):
            return

        # Get organization and project details
        self.organization_data = api.organization.get_organization(
            settings.selected_organization_id
        )
        self.project_data = api.project.get_project(settings.selected_project_id)

        # 選択中のProjectは配下のProjectノードとして表示するため、ルートは組織名まで
        self.setName(f"{constants.PLUGIN_NAME}: {self.organization_data.name}")

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

        actions = []

        # ルートは選択中Organizationを表す。組織の切り替えはここから。
        select_organization_action = QAction(i18n.tr("Select Organization"), parent)
        select_organization_action.triggered.connect(self.select_organization)
        actions.append(select_organization_action)

        # プロジェクトの切り替えは通常Projectノード側から行うが、未選択で
        # Projectノードが無いときは入口としてルートにも出す。
        if self.project_data is None:
            select_project_action = QAction(i18n.tr("Select Project"), parent)
            select_project_action.triggered.connect(self.select_project)
            actions.append(select_project_action)

        # Refresh action
        refresh_action = QAction(i18n.tr("Refresh"), parent)
        refresh_action.triggered.connect(self.refresh)
        actions.append(refresh_action)

        # Account action
        account_action = QAction(i18n.tr("Account"), parent)
        account_action.triggered.connect(self.account_settings)
        actions.append(account_action)

        return actions

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
            # ログイン直後はまず組織を選び、続けてプロジェクトを選ぶ
            self.select_organization()

    def _confirm_discard_if_dirty(self) -> bool:
        """未保存の変更があれば破棄確認する。続行してよければ True。"""
        if not QgsProject.instance().isDirty():
            return True
        return (
            QMessageBox.question(
                None,
                i18n.tr("Change Project"),
                i18n.tr(
                    "Switching projects will discard the current map state. Continue?"
                ),
                Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
                Q_MESSAGEBOX_STD_BUTTON.No,
            )
            == Q_MESSAGEBOX_STD_BUTTON.Yes
        )

    def select_organization(self):
        """Select an organization. On change, clear the project and pick a new one."""
        if not self._confirm_discard_if_dirty():
            return

        prev_org_id = get_settings().selected_organization_id

        # ダイアログは初回のみ生成し、以降は再読み込みして再利用する
        try:
            if self.organization_select_dialog is None:
                self.organization_select_dialog = OrganizationSelectDialog()
            else:
                self.organization_select_dialog.reload_dialog()
        except Exception as e:
            handle_api_error(
                e,
                parent=None,
                log_prefix=i18n.tr("Error loading organization selection dialog"),
            )
            return

        if not exec_dialog(self.organization_select_dialog):
            return

        new_org_id = get_settings().selected_organization_id
        if new_org_id == prev_org_id:
            # 組織が変わらなければProjectはそのまま。念のためリフレッシュのみ。
            self.refresh()
            return

        # 組織が変わるとProjectは無効になるのでクリアし、QGIS Projectも初期化する
        store_setting("selected_project_id", "")
        QgsProject.instance().clear()
        self.refresh()
        # 続けて新しい組織のProjectを選んでもらう
        self.select_project()

    def select_project(self):
        """Select a project within the current organization."""
        if not get_settings().selected_organization_id:
            # 組織が未選択ならまず組織選択へ誘導する
            self.select_organization()
            return

        if not self._confirm_discard_if_dirty():
            return

        prev_project_id = get_settings().selected_project_id

        # プロジェクト選択ダイアログは初回時のみ生成、それ以降は再利用する
        try:
            if self.project_select_dialog is None:
                self.project_select_dialog = ProjectSelectDialog()
            else:
                self.project_select_dialog.reload()
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
        if self.organization_data is None or self.project_data is None:
            return [
                ErrorItem(
                    self,
                    i18n.tr("Please select a project"),
                )
            ]

        # 選択中のProjectと組織のCatalogを並列に表示する
        # （サービスの階層 Organization → {Project, Catalog} に対応）
        project_root = ProjectRoot(
            self,
            f"{self.path()}/project",
            self.organization_data,
            self.project_data,
        )
        project_root.setSortKey(0)

        catalog_root = CatalogRoot(
            self,
            i18n.tr("Catalogs"),
            f"{self.path()}/catalogs",
            self.organization_data,
        )
        catalog_root.setSortKey(1)

        return [project_root, catalog_root]
