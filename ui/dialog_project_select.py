import os
from typing import Optional, Tuple

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QT_VERSION_STR, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ..imgs import IMGS_PATH
from ..settings_manager import SettingsManager
from ..strato.api import organization, project
from ..strato.api.organization import Organization
from ..strato.api.project import Project
from ..strato.constants import LOG_CATEGORY

QT_VERSION_INT = int(QT_VERSION_STR.split(".")[0])
QT_USER_ROLE = Qt.UserRole if QT_VERSION_INT <= 5 else Qt.ItemDataRole.UserRole
QT_DIALOG_BUTTON_OK = (
    QDialogButtonBox.Ok if QT_VERSION_INT <= 5 else QDialogButtonBox.StandardButton.Ok
)
QT_DIALOG_BUTTON_CANCEL = (
    QDialogButtonBox.Cancel
    if QT_VERSION_INT <= 5
    else QDialogButtonBox.StandardButton.Cancel
)


class ProjectSelectDialog(QDialog):
    """Dialog for selecting projects from organizations"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Select Project")
        self.resize(500, 400)

        # Store selected project
        self.selected_project = None

        # Load icons
        self.org_icon = QIcon(os.path.join(IMGS_PATH, "icon_organization.svg"))
        self.project_icon = QIcon(os.path.join(IMGS_PATH, "icon_project.svg"))

        # Create layout
        self.setup_ui()

        # Load organizations
        self.load_organizations()

        # Load previously selected project
        self.load_saved_selection()

    def setup_ui(self):
        """Set up the dialog UI"""
        layout = QVBoxLayout()

        # Organization selection
        org_layout = QHBoxLayout()
        org_layout.addWidget(QLabel("Organization:"))
        self.org_combo = QComboBox()
        self.org_combo.currentIndexChanged.connect(self.on_organization_changed)
        org_layout.addWidget(self.org_combo)
        layout.addLayout(org_layout)

        # Project tree
        layout.addWidget(QLabel("Projects:"))
        self.project_tree = QTreeWidget()
        self.project_tree.setHeaderHidden(True)
        self.project_tree.itemSelectionChanged.connect(self.on_project_selected)
        layout.addWidget(self.project_tree)

        # Buttons
        button_layout = QHBoxLayout()

        # Refresh button
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        button_layout.addWidget(self.refresh_button)

        button_layout.addStretch()

        # OK/Cancel buttons
        self.button_box = QDialogButtonBox(
            QT_DIALOG_BUTTON_OK | QT_DIALOG_BUTTON_CANCEL
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.button_box.button(QT_DIALOG_BUTTON_OK).setEnabled(False)
        button_layout.addWidget(self.button_box)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def load_organizations(self):
        """Load organizations into the combo box"""
        try:
            # Clear existing items
            self.org_combo.clear()

            # Get organizations
            organizations = organization.get_organizations()

            if not organizations:
                QgsMessageLog.logMessage(
                    "No organizations available", LOG_CATEGORY, Qgis.Warning
                )
                return

            # Add organizations to combo box
            for org in organizations:
                self.org_combo.addItem(org.name, org)

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error loading organizations: {str(e)}", LOG_CATEGORY, Qgis.Critical
            )

    def on_organization_changed(self, index):
        """Handle organization selection change"""
        if index < 0:
            return

        # Get selected organization
        org_data = self.org_combo.itemData(index)
        if not org_data:
            return

        # Load projects for this organization
        self.load_projects(org_data)

    def load_projects(self, org: Organization):
        """Load projects for the selected organization"""
        try:
            # Clear existing items
            self.project_tree.clear()

            # Get projects
            projects = project.get_projects_by_organization(org.id)

            if not projects:
                QgsMessageLog.logMessage(
                    f"No projects available for organization {org.name}",
                    LOG_CATEGORY,
                    Qgis.Warning,
                )
                return

            # Add projects to tree
            for project_item in projects:
                tree_item = QTreeWidgetItem(self.project_tree)
                tree_item.setText(0, project_item.name)
                tree_item.setIcon(0, self.project_icon)
                tree_item.setData(0, QT_USER_ROLE, project_item)

            # Expand all items
            self.project_tree.expandAll()

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error loading projects: {str(e)}", LOG_CATEGORY, Qgis.Critical
            )

    def on_project_selected(self):
        """Handle project selection"""
        selected_items = self.project_tree.selectedItems()
        if not selected_items:
            self.button_box.button(QT_DIALOG_BUTTON_OK).setEnabled(False)
            self.selected_project = None
            return

        # Get selected project
        item = selected_items[0]
        self.selected_project = item.data(0, QT_USER_ROLE)

        # Enable OK button
        self.button_box.button(QT_DIALOG_BUTTON_OK).setEnabled(True)

    def refresh(self):
        """Refresh all data"""
        self.load_organizations()

    def get_selected_project(self) -> Optional[Project]:
        """Get the selected project"""
        return self.selected_project

    def get_selected_organization(
        self,
    ) -> Optional[Organization]:
        """Get the selected organization"""
        org_index = self.org_combo.currentIndex()
        return self.org_combo.itemData(org_index) if org_index >= 0 else None

    def accept(self):
        """Handle dialog acceptance"""
        if self.selected_project:
            # Save selection
            self.save_selection()
            super().accept()

    def save_selection(self):
        """Save the current selection to settings"""
        if not self.selected_project:
            return

        org = self.get_selected_organization()
        if not org:
            return

        settings = SettingsManager()
        settings.store_setting("selected_organization_id", org.id)
        settings.store_setting("selected_project_id", self.selected_project.id)

    def load_saved_selection(self):
        """Load previously saved selection"""
        try:
            settings = SettingsManager()
            org_id = settings.get_setting("selected_organization_id")
            project_id = settings.get_setting("selected_project_id")

            if not org_id or not project_id:
                return

            # Find organization in combo box
            for i in range(self.org_combo.count()):
                org = self.org_combo.itemData(i)
                if org and org.id == org_id:
                    self.org_combo.setCurrentIndex(i)
                    break

            # Find project in tree
            for i in range(self.project_tree.topLevelItemCount()):
                item = self.project_tree.topLevelItem(i)
                project_item = item.data(0, QT_USER_ROLE)
                if project_item and project_item.id == project_id:
                    item.setSelected(True)
                    break

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error loading saved selection: {str(e)}", LOG_CATEGORY, Qgis.Warning
            )
