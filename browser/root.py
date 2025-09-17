import os

from qgis.core import (
    Qgis,
    QgsDataCollectionItem,
    QgsDataItemProvider,
    QgsDataProvider,
    QgsMessageLog,
    QgsProject,
)
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.utils import iface

from ..imgs import IMGS_PATH
from ..settings_manager import get_settings, store_setting
from ..strato import api
from ..strato.constants import BROWSER_ROOT_PATH, LOG_CATEGORY, PLUGIN_NAME
from ..ui.dialog_config import DialogConfig
from ..ui.dialog_project_select import ProjectSelectDialog
from ..version import exec_dialog
from .styledmap import StyledMapRoot
from .utils import ErrorItem
from .vector import DbRoot


class DataItemProvider(QgsDataItemProvider):
    """Provider for STRATO browser items"""

    def __init__(self):
        QgsDataItemProvider.__init__(self)

    def name(self):
        return PLUGIN_NAME

    def capabilities(self):
        return QgsDataProvider.Net

    def createDataItem(self, path, parent):
        return RootCollection()


class RootCollection(QgsDataCollectionItem):
    """Root collection for STRATO browser"""

    def __init__(self):
        # Initialize with default name, will update with project name later
        QgsDataCollectionItem.__init__(self, None, PLUGIN_NAME, BROWSER_ROOT_PATH)
        self.setIcon(QIcon(os.path.join(IMGS_PATH, "icon.svg")))

        # Update name with project if available
        self.update_name_with_project()

    def tr(self, message):
        """Get the translation for a string using Qt translation API"""
        return QCoreApplication.translate("RootCollection", message)

    def actions(self, parent):
        id_token = get_settings().id_token
        if not id_token:
            # Login action
            login_action = QAction("Login", parent)
            login_action.triggered.connect(self.login)
            return [login_action]

        # Select Project action
        select_project_action = QAction(self.tr("Select Project"), parent)
        select_project_action.triggered.connect(self.select_project)

        # Refresh action
        refresh_action = QAction(self.tr("Refresh"), parent)
        refresh_action.triggered.connect(self.refreshChildren)

        # Logout action
        logout_action = QAction("Logout", parent)
        logout_action.triggered.connect(self.logout)

        return [select_project_action, refresh_action, logout_action]

    def refreshChildren(self):
        """Refresh the children of the root collection"""
        self.refresh()
        self.depopulate()

    def login(self):
        """Login to STRATO"""

        # Show config dialog with Supabase login tab
        dialog = DialogConfig()
        result = exec_dialog(dialog)

        if result:
            # Refresh to show projects
            self.refresh()

    def select_project(self):
        """Select a project to display"""

        # プロジェクトを変更すると、現在の編集状態が失われる可能性があるため、ダイアログで確認
        prev_project_id = get_settings().selected_project_id
        if prev_project_id:
            confirmed = QMessageBox.question(
                None,
                self.tr("Change Project"),
                self.tr(
                    "Changing the project may result in loss of current editing state. Do you want to proceed?"
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if confirmed != QMessageBox.Yes:
                return

        try:
            # Check if user is logged in
            id_token = get_settings().id_token

            if not id_token:
                QMessageBox.warning(
                    None,
                    self.tr("Not Logged In"),
                    self.tr(
                        "You must be logged in to select a project. Please login first."
                    ),
                )
                return

            # Show project selection dialog
            dialog = ProjectSelectDialog()
            result = exec_dialog(dialog)

            if result:
                # Get selected project
                organization = dialog.get_selected_organization()
                project = dialog.get_selected_project()
                if project:
                    QgsMessageLog.logMessage(
                        f"Selected project: {project.name}", LOG_CATEGORY, Qgis.Info
                    )
                    # Update browser name with project name
                    self.setName(f"{PLUGIN_NAME}: {project.name}({organization.name})")
                    # Refresh to show the selected project
                    self.depopulate()
                    self.refresh()

                    # 現在と異なるが選択された場合、QGISプロジェクト全体をクリア
                    if prev_project_id != project.id:
                        QgsProject.instance().clear()
                        iface.messageBar().pushSuccess(
                            self.tr("Project Changed"),
                            self.tr(
                                "QGIS project has been cleared due to project change."
                            ),
                        )

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error selecting project: {str(e)}", LOG_CATEGORY, Qgis.Critical
            )

    def logout(self):
        """Logout from STRATO"""
        # ログアウト時にはProjectをクリアするので、確認ダイアログを表示
        confirmed = QMessageBox.question(
            None,
            self.tr("Logout"),
            self.tr(
                "You have unsaved changes in the current project. Logging out will clear the current project. Do you want to proceed?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmed != QMessageBox.Yes:
            return

        # Projectをクリア
        QgsProject.instance().clear()

        try:
            # Clear tokens and selected project
            store_setting("id_token", "")
            store_setting("refresh_token", "")
            store_setting("user_info", "")
            store_setting("selected_project_id", "")
            store_setting("selected_organization_id", "")

            # Reset browser name
            self.setName(PLUGIN_NAME)

            # Refresh to update UI
            self.refresh()

            QgsMessageLog.logMessage("Logged out successfully", LOG_CATEGORY, Qgis.Info)

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error logging out: {str(e)}", LOG_CATEGORY, Qgis.Critical
            )

    def update_name_with_project(self):
        """Update the browser name to include the project name"""
        try:
            # Check if user is logged in
            id_token = get_settings().id_token
            if not id_token:
                self.setName(PLUGIN_NAME)
                return

            # Get selected organization and project ID
            organization_id = get_settings().selected_organization_id
            project_id = get_settings().selected_project_id
            if not project_id:
                self.setName(PLUGIN_NAME)
                return

            # Get organization and project details
            organization_data = api.organization.get_organization(organization_id)
            project_data = api.project.get_project(project_id)

            self.setName(
                f"{PLUGIN_NAME}: {project_data.name}({organization_data.name})"
            )

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error updating name with project: {str(e)}",
                LOG_CATEGORY,
                Qgis.Warning,
            )
            self.setName(PLUGIN_NAME)

    def createChildren(self):
        """Create child items for the root collection"""
        try:
            # Check if user is logged in
            id_token = get_settings().id_token
            if not id_token:
                return []

            # Get selected organization and project ID
            organization_id = get_settings().selected_organization_id
            project_id = get_settings().selected_project_id

            if not project_id:
                return [
                    ErrorItem(
                        self, self.tr("No project selected. Please select a project.")
                    )
                ]

            # Get organization and project details
            organization_data = api.organization.get_organization(organization_id)
            project_data = api.project.get_project(project_id)

            # Update the browser name with project name
            self.setName(
                f"{PLUGIN_NAME}: {project_data.name}({organization_data.name})"
            )

            # Create vector root directly
            children = []
            vector_path = f"{self.path()}/vectors"
            vector_root = DbRoot(self, "Vectors", vector_path)
            children.append(vector_root)

            # Create styled map root
            styled_map_path = f"{self.path()}/styledmaps"
            styled_map_root = StyledMapRoot(self, "Maps", styled_map_path)
            children.append(styled_map_root)

            return children

        except Exception as e:
            return [ErrorItem(self, self.tr("Error: {}").format(str(e)))]
