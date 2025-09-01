import os
from typing import Optional

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ..imgs import IMGS_PATH
from ..settings_manager import get_settings, store_setting
from ..strato import api
from ..strato.constants import LOG_CATEGORY
from ..version import QT_DIALOG_BUTTON_CANCEL, QT_DIALOG_BUTTON_OK, QT_USER_ROLE


class ProjectSelectDialog(QDialog):
    """Dialog for selecting projects from organizations"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Select Project")
        self.resize(500, 400)
        self.selected_project = None
        self.org_icon = QIcon(os.path.join(IMGS_PATH, "icon_organization.svg"))
        self.project_icon = QIcon(os.path.join(IMGS_PATH, "icon_project.svg"))
        self.setup_ui()
        self.load_organizations()
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

        # Project section with new project button
        project_header_layout = QHBoxLayout()
        project_header_layout.addWidget(QLabel("Projects:"))
        project_header_layout.addStretch()
        self.new_project_button = QPushButton("New Project")
        self.new_project_button.clicked.connect(self.create_new_project)
        project_header_layout.addWidget(self.new_project_button)
        layout.addLayout(project_header_layout)

        # Project tree
        self.project_tree = QTreeWidget()
        self.project_tree.setHeaderHidden(True)
        self.project_tree.itemSelectionChanged.connect(self.on_project_selected)
        layout.addWidget(self.project_tree)

        # Buttons
        button_layout = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        button_layout.addWidget(self.refresh_button)
        button_layout.addStretch()

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
            self.org_combo.clear()
            organizations = api.organization.get_organizations()
            for org in organizations:
                self.org_combo.addItem(org.name, org)
        except Exception as e:
            self._log_error("Error loading organizations", e)

    def on_organization_changed(self, index):
        """Handle organization selection change"""
        if index >= 0 and (org_data := self.org_combo.itemData(index)):
            self.load_projects(org_data)

    def load_projects(self, org: api.organization.Organization):
        """Load projects for the selected organization"""
        try:
            self.project_tree.clear()
            projects = api.project.get_projects_by_organization(org.id)
            for project_item in projects:
                tree_item = QTreeWidgetItem(self.project_tree)
                tree_item.setText(0, project_item.name)
                tree_item.setIcon(0, self.project_icon)
                tree_item.setData(0, QT_USER_ROLE, project_item)
            self.project_tree.expandAll()
        except Exception as e:
            self._log_error("Error loading projects", e)

    def on_project_selected(self):
        """Handle project selection"""
        selected_items = self.project_tree.selectedItems()
        self.selected_project = (
            selected_items[0].data(0, QT_USER_ROLE) if selected_items else None
        )
        self.button_box.button(QT_DIALOG_BUTTON_OK).setEnabled(
            bool(self.selected_project)
        )

    def refresh(self):
        """Refresh all data"""
        if org := self.get_selected_organization():
            self.load_projects(org)

    def get_selected_project(self) -> Optional[api.project.Project]:
        """Get the selected project"""
        return self.selected_project

    def get_selected_organization(self) -> Optional[api.organization.Organization]:
        """Get the selected organization"""
        return (
            self.org_combo.currentData() if self.org_combo.currentIndex() >= 0 else None
        )

    def accept(self):
        """Handle dialog acceptance"""
        if self.selected_project:
            self.save_selection()
            super().accept()

    def save_selection(self):
        """Save the current selection to settings"""
        if self.selected_project and (org := self.get_selected_organization()):
            store_setting("selected_organization_id", org.id)
            store_setting("selected_project_id", self.selected_project.id)

    def load_saved_selection(self):
        """Load previously saved selection"""
        try:
            org_id = get_settings().selected_organization_id
            project_id = get_settings().selected_project_id
            if not org_id or not project_id:
                return
            self._select_organization_by_id(org_id)
            self._select_project_by_id(project_id)
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error loading saved selection: {str(e)}", LOG_CATEGORY, Qgis.Warning
            )

    def create_new_project(self):
        """Create a new project in the selected organization"""
        if not (org := self.get_selected_organization()):
            QMessageBox.warning(
                self, "No Organization Selected", "Please select an organization first."
            )
            return

        project_name, ok = QInputDialog.getText(
            self, "New Project", f"Enter project name for organization '{org.name}':"
        )
        if not ok or not project_name:
            return

        try:
            new_project = api.project.create_project(
                organization_id=org.id, name=project_name
            )
            QgsMessageLog.logMessage(
                f"Successfully created project '{project_name}'",
                LOG_CATEGORY,
                Qgis.Info,
            )
            self.refresh()
            self._select_project_by_id(new_project.id)
            QMessageBox.information(
                self,
                "Project Created",
                f"Project '{project_name}' has been created successfully.",
            )
        except Exception as e:
            self._log_error("Failed to create project", e, show_dialog=True)

    def _select_organization_by_id(self, org_id: str):
        """Select organization by ID in combo box"""
        for i in range(self.org_combo.count()):
            if (org := self.org_combo.itemData(i)) and org.id == org_id:
                self.org_combo.setCurrentIndex(i)
                break

    def _select_project_by_id(self, project_id: str):
        """Select project by ID in tree"""
        for i in range(self.project_tree.topLevelItemCount()):
            item = self.project_tree.topLevelItem(i)
            if (project := item.data(0, QT_USER_ROLE)) and project.id == project_id:
                item.setSelected(True)
                break

    def _log_error(self, message: str, error: Exception, show_dialog: bool = False):
        """Log error and optionally show dialog"""
        QgsMessageLog.logMessage(
            f"{message}: {str(error)}", LOG_CATEGORY, Qgis.Critical
        )
        if show_dialog:
            QMessageBox.critical(self, "Error", f"{message}: {str(error)}")
