import os
import webbrowser
from datetime import datetime
from typing import Optional

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QCursor, QFont, QIcon
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..imgs import IMGS_PATH
from ..settings_manager import get_settings, store_setting
from ..strato import api
from ..strato.api.config import get_api_config
from ..strato.constants import LOG_CATEGORY
from ..version import QT_DIALOG_BUTTON_CANCEL, QT_DIALOG_BUTTON_OK, QT_USER_ROLE


class ProjectItemWidget(QWidget):
    """Custom widget for displaying project information in a card-like layout"""

    def __init__(self, project, project_icon, parent_dialog=None):
        super().__init__()
        self.project = project
        self.parent_dialog = parent_dialog
        self.setMinimumHeight(80)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
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
        counts_label = QLabel(
            f"Vectors: {self.project.vectorCount}  |  Maps: {self.project.mapCount}"
        )
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
            dt = datetime.fromisoformat(date_string.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, AttributeError):
            return date_string

    def show_context_menu(self, position):
        """Show context menu for project item"""
        menu = QMenu(self)

        # Open in Web action
        open_web_action = menu.addAction("Open in Web UI")
        open_web_action.triggered.connect(self.open_in_web)
        
        # Edit action
        edit_action = menu.addAction("Edit Project")
        edit_action.triggered.connect(self.edit_project)

        menu.addSeparator()

        # Delete action
        delete_action = menu.addAction("Delete Project")
        delete_action.triggered.connect(self.delete_project)

        menu.exec_(self.mapToGlobal(position))

    def open_in_web(self):
        """Open project in web browser"""
        if not self.project:
            return

        config = get_api_config()
        base_url = config.SERVER_URL.replace("/api", "")
        project_url = f"{base_url}/projects/{self.project.id}"

        try:
            webbrowser.open(project_url)
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error opening web browser: {str(e)}", LOG_CATEGORY, Qgis.Critical
            )

    def delete_project(self):
        """Delete project with confirmation"""
        if not self.project or not self.parent_dialog:
            return

        # Show confirmation dialog
        reply = QMessageBox.question(
            self.parent_dialog,
            "Delete Project",
            f"Are you sure you want to delete project '{self.project.name}'?\n"
            "This action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            try:
                # Call API to delete project
                api.project.delete_project(self.project.id)

                QgsMessageLog.logMessage(
                    f"Successfully deleted project '{self.project.name}'",
                    LOG_CATEGORY,
                    Qgis.Info,
                )

                # Refresh the project list
                if self.parent_dialog:
                    org = self.parent_dialog.get_selected_organization()
                    if org:
                        self.parent_dialog.load_organization_detail(org)
                        self.parent_dialog.load_projects(org)

                QMessageBox.information(
                    self.parent_dialog,
                    "Project Deleted",
                    f"Project '{self.project.name}' has been deleted successfully.",
                )
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Failed to delete project: {str(e)}", LOG_CATEGORY, Qgis.Critical
                )
                QMessageBox.critical(
                    self.parent_dialog, "Error", f"Failed to delete project: {str(e)}"
                )
    
    def edit_project(self):
        """Edit project metadata"""
        if not self.project or not self.parent_dialog:
            return
        
        # Show input dialog with current project name
        new_name, ok = QInputDialog.getText(
            self.parent_dialog,
            "Edit Project",
            "Project name:",
            text=self.project.name
        )
        
        if ok and new_name and new_name != self.project.name:
            try:
                # Call API to update project
                updated_project = api.project.update_project(
                    project_id=self.project.id,
                    name=new_name
                )
                
                QgsMessageLog.logMessage(
                    f"Successfully updated project '{self.project.name}' to '{new_name}'",
                    LOG_CATEGORY,
                    Qgis.Info,
                )
                
                # Update the current project data
                self.project = updated_project
                
                # Refresh the project list
                if self.parent_dialog:
                    org = self.parent_dialog.get_selected_organization()
                    if org:
                        self.parent_dialog.load_projects(org)
                        # Re-select the updated project
                        self.parent_dialog._select_project_by_id(self.project.id)
                
                QMessageBox.information(
                    self.parent_dialog,
                    "Project Updated",
                    f"Project has been renamed to '{new_name}' successfully."
                )
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Failed to update project: {str(e)}", LOG_CATEGORY, Qgis.Critical
                )
                QMessageBox.critical(
                    self.parent_dialog, "Error", f"Failed to update project: {str(e)}"
                )


class ProjectSelectDialog(QDialog):
    """Dialog for selecting projects from organizations"""

    # UI Constants
    LABEL_WIDTH = 80
    USAGE_TEXT_WIDTH = 100
    PROGRESS_HEIGHT = 8

    # Style Constants
    LABEL_STYLE = "font-size: 12px; color: #495057;"
    INFO_STYLE = "font-size: 11px; color: #666;"

    # Color thresholds
    COLOR_RED_THRESHOLD = 90
    COLOR_ORANGE_THRESHOLD = 75

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Select Project")
        self.resize(500, 500)
        self.selected_project = None
        self.current_org_id = None
        self.org_icon = QIcon(os.path.join(IMGS_PATH, "icon_organization.svg"))
        self.project_icon = QIcon(os.path.join(IMGS_PATH, "icon_project.svg"))
        self.setup_ui()
        self.load_organizations()
        self.load_saved_selection()

    def setup_ui(self):
        """Set up the dialog UI"""
        layout = QVBoxLayout()

        self._create_organization_selector(layout)
        self._create_usage_panel(layout)
        self._create_project_section(layout)
        self._create_button_panel(layout)

        self.setLayout(layout)

    def _create_organization_selector(self, parent_layout: QVBoxLayout):
        """Create organization selection combo box"""
        org_layout = QHBoxLayout()
        org_layout.addWidget(QLabel("Organization:"))

        self.org_combo = QComboBox()
        self.org_combo.currentIndexChanged.connect(self.on_organization_changed)
        org_layout.addWidget(self.org_combo)

        parent_layout.addLayout(org_layout)

    def _create_usage_panel(self, parent_layout: QVBoxLayout):
        """Create organization usage panel with progress bars"""
        self.usage_frame = QFrame()
        self.usage_frame.setFrameStyle(QFrame.NoFrame)
        self.usage_frame.setVisible(False)

        usage_layout = QVBoxLayout()
        usage_layout.setSpacing(10)

        self.usage_widgets = {}
        self._create_usage_rows(usage_layout)
        self._create_plan_info_row(usage_layout)

        self.usage_frame.setLayout(usage_layout)
        parent_layout.addWidget(self.usage_frame)

    def _create_usage_rows(self, parent_layout: QVBoxLayout):
        """Create usage progress bars for each resource"""
        resources = [
            ("projects", "Projects"),
            ("maps", "Maps"),
            ("vectors", "Vectors"),
            ("members", "Members"),
            ("storage", "Storage"),
        ]

        for key, label in resources:
            row_layout = self._create_usage_row(key, label)
            parent_layout.addLayout(row_layout)

    def _create_usage_row(self, key: str, label: str) -> QHBoxLayout:
        """Create a single usage row with label, text and progress bar"""
        row_layout = QHBoxLayout()
        row_layout.setSpacing(10)

        # Resource label
        resource_label = QLabel(label)
        resource_label.setFixedWidth(self.LABEL_WIDTH)
        resource_label.setStyleSheet(self.LABEL_STYLE)
        row_layout.addWidget(resource_label)

        # Usage text
        usage_text = QLabel()
        usage_text.setFixedWidth(self.USAGE_TEXT_WIDTH)
        usage_text.setAlignment(Qt.AlignRight)
        row_layout.addWidget(usage_text)

        # Progress bar
        progress_bar = self._create_progress_bar()
        row_layout.addWidget(progress_bar, 1)  # Stretch factor 1

        self.usage_widgets[key] = {"label": usage_text, "progress": progress_bar}
        return row_layout

    def _create_progress_bar(self) -> QProgressBar:
        """Create a styled progress bar"""
        progress_bar = QProgressBar()
        progress_bar.setTextVisible(False)
        progress_bar.setMinimumHeight(self.PROGRESS_HEIGHT)
        progress_bar.setMaximumHeight(self.PROGRESS_HEIGHT)
        progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 4px;
                background-color: #f5f5f5;
            }
            QProgressBar::chunk {
                background-color: #4caf50;
                border-radius: 3px;
            }
        """)
        return progress_bar

    def _create_plan_info_row(self, parent_layout: QVBoxLayout):
        """Create plan and role information row"""
        info_layout = QHBoxLayout()
        info_layout.setContentsMargins(0, 10, 0, 0)
        info_layout.addStretch()

        self.plan_label = self._create_info_label()
        info_layout.addWidget(self.plan_label)

        self.role_label = self._create_info_label()
        info_layout.addWidget(self.role_label)

        # Add Web UI link
        self.web_link = QLabel("<a href='#'>Open in Web</a>")
        self.web_link.setStyleSheet(self.INFO_STYLE + " color: #0066cc;")
        self.web_link.setCursor(QCursor(Qt.PointingHandCursor))
        self.web_link.linkActivated.connect(self._open_web_ui)
        info_layout.addWidget(self.web_link)

        parent_layout.addLayout(info_layout)

    def _create_info_label(self) -> QLabel:
        """Create a styled info label"""
        label = QLabel()
        label.setStyleSheet(self.INFO_STYLE)
        return label

    def _create_project_section(self, parent_layout: QVBoxLayout):
        """Create project list section with header"""
        # Header with new project button
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("Projects:"))
        header_layout.addStretch()

        self.new_project_button = QPushButton("New Project")
        self.new_project_button.clicked.connect(self.create_new_project)
        header_layout.addWidget(self.new_project_button)
        parent_layout.addLayout(header_layout)

        # Project list
        self.project_list = self._create_project_list()
        parent_layout.addWidget(self.project_list)

    def _create_project_list(self) -> QListWidget:
        """Create styled project list widget"""
        project_list = QListWidget()
        project_list.setSpacing(4)
        project_list.setStyleSheet("""
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
        project_list.itemSelectionChanged.connect(self.on_project_selected)
        return project_list

    def _create_button_panel(self, parent_layout: QVBoxLayout):
        """Create bottom button panel"""
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.button_box = QDialogButtonBox(
            QT_DIALOG_BUTTON_OK | QT_DIALOG_BUTTON_CANCEL
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.button_box.button(QT_DIALOG_BUTTON_OK).setEnabled(False)
        button_layout.addWidget(self.button_box)

        parent_layout.addLayout(button_layout)

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
            self.load_organization_detail(org_data)
            self.load_projects(org_data)

    def load_organization_detail(self, org: api.organization.Organization):
        """Load and display organization detail including usage"""
        try:
            # Store current organization ID
            self.current_org_id = org.id
            # Fetch organization details
            org_detail = api.organization.get_organization(org.id)
            # Update usage display
            self.update_usage_display(org_detail)
            self.usage_frame.setVisible(True)
        except Exception as e:
            self._log_error("Error loading organization details", e)
            self.usage_frame.setVisible(False)

    def update_usage_display(self, org_detail: api.organization.OrganizationDetail):
        """Update the usage display with organization details"""
        # Get plan limits from API
        try:
            plan_type = org_detail.subscriptionPlan
            plan_limits = api.plan.get_plan_limits(plan_type)
        except Exception as e:
            self._log_error("Error fetching plan limits", e)
            # Fallback to reasonable defaults if API fails
            plan_limits = api.plan.PlanLimits(
                maxProjects=0,
                maxVectors=0,
                maxStyledMaps=0,
                maxOrganizationMembers=0,
                maxVectorFeatures=0,
                maxVectorAttributes=0,
            )

        # Define resource mappings
        resource_mappings = [
            ("projects", org_detail.usage.projects, plan_limits.maxProjects),
            ("maps", org_detail.usage.styledMaps, plan_limits.maxStyledMaps),
            ("vectors", org_detail.usage.vectors, plan_limits.maxVectors),
            (
                "members",
                org_detail.usage.organizationMembers,
                plan_limits.maxOrganizationMembers,
            ),
        ]

        # Update each resource
        for key, used, limit in resource_mappings:
            self._update_usage_widget(key, used, limit)

        # Update Storage
        if "storage" in self.usage_widgets:
            used = org_detail.usage.usedStorageUnits
            total = org_detail.storageUnits
            # Format storage units with appropriate suffix
            used_str = self._format_storage_units(used)
            total_str = self._format_storage_units(total)
            self.usage_widgets["storage"]["label"].setText(f"{used_str} / {total_str}")
            if total > 0:
                self.usage_widgets["storage"]["progress"].setMaximum(total)
                self.usage_widgets["storage"]["progress"].setValue(used)
                self._set_progress_color(
                    self.usage_widgets["storage"]["progress"], used, total
                )

        # Update plan and role labels
        self.plan_label.setText(f"Plan: {org_detail.subscriptionPlan}")
        self.role_label.setText(f"Role: {org_detail.role}")

    def _update_usage_widget(self, key: str, used: int, limit: int):
        """Update a single usage widget with values and colors"""
        if key not in self.usage_widgets:
            return

        widgets = self.usage_widgets[key]
        widgets["label"].setText(f"{used} / {limit}")
        widgets["progress"].setMaximum(limit)
        widgets["progress"].setValue(used)
        self._set_progress_color(widgets["progress"], used, limit)

    def _set_progress_color(self, progress_bar: QProgressBar, used: int, limit: int):
        """Set progress bar color based on usage percentage"""
        percentage = (used / limit * 100) if limit > 0 else 0

        # Determine color based on usage percentage
        color = self._get_usage_color(percentage)

        progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: none;
                border-radius: 4px;
                background-color: #f5f5f5;
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 3px;
            }}
        """)

    def _get_usage_color(self, percentage: float) -> str:
        """Get color based on usage percentage"""
        if percentage >= self.COLOR_RED_THRESHOLD:
            return "#f44336"  # Red
        elif percentage >= self.COLOR_ORANGE_THRESHOLD:
            return "#ff9800"  # Orange
        return "#4caf50"  # Green

    def _open_web_ui(self):
        """Open the organization page in web browser"""
        if not self.current_org_id:
            return

        config = get_api_config()
        # Remove /api from the server URL if present
        base_url = config.SERVER_URL.replace("/api", "")
        org_url = f"{base_url}/organization?id={self.current_org_id}"

        try:
            webbrowser.open(org_url)
        except Exception as e:
            self._log_error("Error opening web browser", e)

    def _format_storage_units(self, units: float) -> str:
        """Format storage units with appropriate suffix"""
        if units < 1:
            return f"{units:.2f}SU"
        elif units < 1000:
            return f"{units:.0f}SU"
        else:
            return f"{units / 1000:.1f}KSU"

    def load_projects(self, org: api.organization.Organization):
        """Load projects for the selected organization"""
        try:
            self.project_list.clear()
            projects = api.project.get_projects_by_organization(org.id)

            for project_item in projects:
                # Create custom widget
                item_widget = ProjectItemWidget(project_item, self.project_icon, self)

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
        self.selected_project = (
            current_item.data(QT_USER_ROLE) if current_item else None
        )
        self.button_box.button(QT_DIALOG_BUTTON_OK).setEnabled(
            bool(self.selected_project)
        )

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
            # refresh project list and select the new project
            self.load_organization_detail(org)
            self.load_projects(org)
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
            if (
                item
                and (project := item.data(QT_USER_ROLE))
                and project.id == project_id
            ):
                self.project_list.setCurrentItem(item)
                break

    def _log_error(self, message: str, error: Exception, show_dialog: bool = False):
        """Log error and optionally show dialog"""
        QgsMessageLog.logMessage(
            f"{message}: {str(error)}", LOG_CATEGORY, Qgis.Critical
        )
        if show_dialog:
            QMessageBox.critical(self, "Error", f"{message}: {str(error)}")
