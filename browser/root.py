import os

from PyQt5.QtCore import QCoreApplication
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QAction, QMessageBox
from qgis.core import (
    Qgis,
    QgsDataCollectionItem,
    QgsDataItem,
    QgsDataItemProvider,
    QgsDataProvider,
    QgsMessageLog,
)
from qgis.utils import iface

from ..imgs import IMGS_PATH
from ..qgishub import api
from ..qgishub.config import config
from ..qgishub.constants import BROWSER_ROOT_PATH, LOG_CATEGORY, PLUGIN_NAME
from ..settings_manager import SettingsManager
from ..ui.dialog_config import DialogConfig
from ..ui.dialog_project_select import ProjectSelectDialog
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
        actions = []

        # Login action
        login_action = QAction("Login", parent)
        login_action.triggered.connect(self.login)
        actions.append(login_action)

        # Logout action
        logout_action = QAction("Logout", parent)
        logout_action.triggered.connect(self.logout)
        actions.append(logout_action)

        # Select Project action
        select_project_action = QAction(self.tr("Select Project"), parent)
        select_project_action.triggered.connect(self.select_project)
        actions.append(select_project_action)

        # Refresh action
        refresh_action = QAction(self.tr("Refresh"), parent)
        refresh_action.triggered.connect(self.refresh)
        actions.append(refresh_action)

        return actions

    def login(self):
        """Login to STRATO"""

        # Show config dialog with Supabase login tab
        dialog = DialogConfig()
        result = dialog.exec_()

        if result:
            # Refresh to show projects
            iface.browserModel().reload()

    def select_project(self):
        """Select a project to display"""
        try:
            # Check if user is logged in
            settings = SettingsManager()
            id_token = settings.get_setting("id_token")

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
            result = dialog.exec_()

            if result:
                # Get selected project
                project = dialog.get_selected_project()
                if project:
                    QgsMessageLog.logMessage(
                        f"Selected project: {project.name}", LOG_CATEGORY, Qgis.Info
                    )
                    # Update browser name with project name
                    self.setName(f"{PLUGIN_NAME}: {project.name}")
                    # Refresh to show the selected project
                    self.depopulate()
                    self.refresh()

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error selecting project: {str(e)}", LOG_CATEGORY, Qgis.Critical
            )

    def logout(self):
        """Logout from STRATO"""
        try:
            # Clear tokens and selected project
            config.refresh()
            settings_manager = SettingsManager()
            settings_manager.store_setting("id_token", "")
            settings_manager.store_setting("refresh_token", "")
            settings_manager.store_setting("user_info", "")
            settings_manager.store_setting("selected_project_id", "")
            settings_manager.store_setting("selected_organization_id", "")

            # Reset browser name
            self.setName(PLUGIN_NAME)

            # Refresh to update UI
            iface.browserModel().reload()

            QgsMessageLog.logMessage("Logged out successfully", LOG_CATEGORY, Qgis.Info)

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error logging out: {str(e)}", LOG_CATEGORY, Qgis.Critical
            )

    def update_name_with_project(self):
        """Update the browser name to include the project name"""
        try:
            # Check if user is logged in
            settings = SettingsManager()
            id_token = settings.get_setting("id_token")
            if not id_token:
                self.setName(PLUGIN_NAME)
                return

            # Get selected project ID
            project_id = settings.get_setting("selected_project_id")
            if not project_id:
                self.setName(PLUGIN_NAME)
                return

            # Get project details
            project_data = api.project.get_project(project_id)
            if project_data:
                self.setName(f"{PLUGIN_NAME}: {project_data.name}")
            else:
                self.setName(PLUGIN_NAME)

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
            settings = SettingsManager()
            id_token = settings.get_setting("id_token")

            if not id_token:
                return [ErrorItem(self, self.tr("Not Logged In"))]

            # Get selected project ID
            project_id = settings.get_setting("selected_project_id")

            if not project_id:
                return [
                    ErrorItem(
                        self, self.tr("No project selected. Please select a project.")
                    )
                ]

            # Get project details
            project_data = api.project.get_project(project_id)

            if not project_data:
                return [
                    ErrorItem(
                        self,
                        self.tr("Project not found. Please select another project."),
                    )
                ]

            # Update the browser name with project name
            self.setName(f"{PLUGIN_NAME}: {project_data.name}")

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
