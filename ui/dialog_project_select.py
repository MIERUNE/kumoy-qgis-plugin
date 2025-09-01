import os
from datetime import datetime
from typing import Optional

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QIcon, QFont
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..imgs import IMGS_PATH
from ..settings_manager import get_settings, store_setting
from ..strato import api
from ..strato.constants import LOG_CATEGORY
from ..version import QT_DIALOG_BUTTON_CANCEL, QT_DIALOG_BUTTON_OK, QT_USER_ROLE


class ProjectItemWidget(QWidget):
    """Custom widget for displaying project information in a card-like layout"""
    
    def __init__(self, project, project_icon):
        super().__init__()
        self.project = project
        self.setMinimumHeight(80)
        self.setup_ui(project_icon)
    
    def setup_ui(self, project_icon):
        """Set up the project item UI"""
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Thumbnail placeholder
        thumbnail_label = QLabel()
        pixmap = project_icon.pixmap(QSize(60, 60))
        thumbnail_label.setPixmap(pixmap)
        thumbnail_label.setFixedSize(60, 60)
        thumbnail_label.setScaledContents(True)
        thumbnail_label.setStyleSheet("""
            QLabel {
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 2px;
                background-color: #f8f8f8;
            }
        """)
        main_layout.addWidget(thumbnail_label)
        
        # Project info layout
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)
        
        # Project name
        name_label = QLabel(self.project.name)
        name_font = QFont()
        name_font.setPointSize(12)
        name_font.setBold(True)
        name_label.setFont(name_font)
        name_label.setStyleSheet("color: #333;")
        info_layout.addWidget(name_label)
        
        # Vector and Map counts
        counts_label = QLabel(f"Vectors: {self.project.vectorCount}  |  Maps: {self.project.mapCount}")
        counts_label.setStyleSheet("color: #666; font-size: 11px;")
        info_layout.addWidget(counts_label)
        
        # Last updated
        updated_text = self._format_date(self.project.updatedAt)
        updated_label = QLabel(f"Last updated: {updated_text}")
        updated_label.setStyleSheet("color: #999; font-size: 10px;")
        info_layout.addWidget(updated_label)
        
        info_layout.addStretch()
        main_layout.addLayout(info_layout)
        main_layout.addStretch()
        
        self.setLayout(main_layout)
        
        # Add hover effect
        self.setStyleSheet("""
            ProjectItemWidget {
                background-color: white;
                border-radius: 4px;
            }
            ProjectItemWidget:hover {
                background-color: #f0f8ff;
            }
        """)
    
    def _format_date(self, date_string: str) -> str:
        """Format ISO date string to readable format"""
        if not date_string:
            return "Never"
        try:
            dt = datetime.fromisoformat(date_string.replace('Z', '+00:00'))
            return dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, AttributeError):
            return date_string


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

        # Project list with custom items
        self.project_list = QListWidget()
        self.project_list.setSpacing(4)
        self.project_list.setStyleSheet("""
            QListWidget {
                background-color: #f5f5f5;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 4px;
            }
            QListWidget::item {
                background-color: white;
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                margin: 2px;
            }
            QListWidget::item:selected {
                background-color: #e3f2fd;
                border: 1px solid #2196F3;
            }
            QListWidget::item:hover {
                background-color: #f0f8ff;
                border: 1px solid #b0d4ff;
            }
        """)
        self.project_list.itemSelectionChanged.connect(self.on_project_selected)
        layout.addWidget(self.project_list)

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
            self.project_list.clear()
            projects = api.project.get_projects_by_organization(org.id)
            
            for project_item in projects:
                # Create custom widget
                item_widget = ProjectItemWidget(project_item, self.project_icon)
                
                # Create list item
                list_item = QListWidgetItem(self.project_list)
                list_item.setSizeHint(item_widget.sizeHint())
                list_item.setData(QT_USER_ROLE, project_item)
                
                # Set the custom widget
                self.project_list.addItem(list_item)
                self.project_list.setItemWidget(list_item, item_widget)
                
        except Exception as e:
            self._log_error("Error loading projects", e)

    def on_project_selected(self):
        """Handle project selection"""
        current_item = self.project_list.currentItem()
        self.selected_project = current_item.data(QT_USER_ROLE) if current_item else None
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
        """Select project by ID in list"""
        for i in range(self.project_list.count()):
            item = self.project_list.item(i)
            if item and (project := item.data(QT_USER_ROLE)) and project.id == project_id:
                self.project_list.setCurrentItem(item)
                break

    def _log_error(self, message: str, error: Exception, show_dialog: bool = False):
        """Log error and optionally show dialog"""
        QgsMessageLog.logMessage(
            f"{message}: {str(error)}", LOG_CATEGORY, Qgis.Critical
        )
        if show_dialog:
            QMessageBox.critical(self, "Error", f"{message}: {str(error)}")
