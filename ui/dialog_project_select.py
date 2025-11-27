import math
import webbrowser
from datetime import datetime
from typing import Optional

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
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

from ..imgs import MAP_ICON, RELOAD_ICON, VECTOR_ICON
from ..pyqt_version import QT_USER_ROLE
from ..settings_manager import get_settings, store_setting
from ..kumoy import api
from ..kumoy.api.error import format_api_error
from ..kumoy.constants import LOG_CATEGORY
from .remote_image_label import RemoteImageLabel


def _get_usage_color(percentage: float) -> str:
    """Get color based on usage percentage"""
    # Color thresholds
    if percentage >= 80:
        return "#f44336"  # Red
    elif percentage >= 75:
        return "#ffa726"  # Orange
    return "#8bc34a"  # Green


class ProjectSelectDialog(QDialog):
    """Dialog for selecting projects from organizations"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.tr("Select Project"))
        self.resize(550, 600)
        self.setMinimumWidth(500)
        self.selected_project = None
        self.current_org_id = None
        self.details_visible = False
        self.setup_ui()
        self.load_user_info()
        self.load_organizations()
        self.load_saved_selection()

    def tr(self, message):
        """Get the translation for a string using Qt translation API"""
        return QCoreApplication.translate("ProjectSelectDialog", message)

    def setup_ui(self):
        """Set up the dialog UI"""
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        ### account / organization
        self.account_org_panel = self._create_account_org_panel()
        layout.addLayout(self.account_org_panel["layout"])

        # Organization詳細パネル
        self.org_details_panel = self._create_org_details_panel()
        layout.addWidget(self.org_details_panel["usage_frame"])
        self.org_details_panel["usage_frame"].setVisible(self.details_visible)

        # Project一覧パネル
        self.project_section = self._create_project_section()
        layout.addWidget(self.project_section["project_list"])

        # 末尾ボタン類
        self.button_panel = self._create_button_panel()
        layout.addLayout(self.button_panel["layout"])

        self.setLayout(layout)

    def _create_account_org_panel(self):
        account_org_layout = QGridLayout()
        # Account label
        account_label = QLabel(self.tr("Account"))
        account_org_layout.addWidget(account_label, 0, 0, 1, 2)
        # Avatar and user name
        avatar_name_layout = QHBoxLayout()
        avatar_label = RemoteImageLabel(size=(32, 32))
        avatar_label.set_circular_mask()
        avatar_label.setAlignment(Qt.AlignCenter)

        avatar_name_layout.addWidget(avatar_label)

        # User name label
        user_name_label = QLabel(self.tr("Loading..."))
        avatar_name_layout.addWidget(user_name_label)
        account_org_layout.addLayout(avatar_name_layout, 1, 0, 1, 2)
        # Organization label
        org_label = QLabel(self.tr("Organization"))
        account_org_layout.addWidget(org_label, 0, 2)
        # "show details" link
        details_toggle = QLabel(self.tr("<a href='#'>Show details &#9660;</a>"))
        details_toggle.setAlignment(Qt.AlignRight)
        details_toggle.linkActivated.connect(self.toggle_details)
        account_org_layout.addWidget(details_toggle, 0, 3)
        # Organization selector
        org_combo = QComboBox()
        org_combo.setMinimumHeight(32)
        org_combo.setStyleSheet(
            """
            QComboBox {
                border: 1px solid #ced4da;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }
        """
        )
        org_combo.currentIndexChanged.connect(self.on_organization_changed)
        account_org_layout.addWidget(org_combo, 1, 2, 1, 2)

        return {
            "layout": account_org_layout,
            "avatar_label": avatar_label,
            "user_name_label": user_name_label,
            "org_combo": org_combo,
            "details_toggle": details_toggle,
        }

    def _create_org_details_panel(self):
        """Create organization usage panel with progress bars"""
        usage_frame = QFrame()
        usage_layout = QVBoxLayout()

        # header layout
        header_layout = QHBoxLayout()
        # plan/role
        plan_role_label = QLabel(
            "<div>\
            <span>{plan}</span><br />\
            <span>{role}</span>\
        </div>"
        )
        header_layout.addWidget(plan_role_label)
        # Organization Settings link
        org_settings_button = QPushButton(self.tr("Organization Settings"))
        org_settings_button.clicked.connect(self.open_organization_settings)
        header_layout.addWidget(org_settings_button)

        usage_layout.addLayout(header_layout)

        # usage
        usage_widgets = {}
        resources = [
            ("projects", "Projects"),
            ("maps", "Maps"),
            ("vectors", "Vectors"),
            ("members", "Members"),
            ("storage", "Storage"),
        ]

        for key, label in resources:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(10)

            # Resource label
            resource_label = QLabel(label)
            resource_label.setFixedWidth(80)
            row_layout.addWidget(resource_label)

            # Usage text
            usage_text = QLabel()
            usage_text.setFixedWidth(120)
            usage_text.setAlignment(Qt.AlignRight)
            row_layout.addWidget(usage_text)

            # Progress bar
            progress_bar = QProgressBar()
            progress_bar.setTextVisible(False)
            progress_bar.setMinimumHeight(6)
            progress_bar.setMaximumHeight(6)
            progress_bar.setStyleSheet(
                """
                QProgressBar {
                    border: none;
                    border-radius: 3px;
                    background-color: #e0e0e0;
                }
                QProgressBar::chunk {
                    background-color: #8bc34a;
                    border-radius: 3px;
                }
            """
            )
            row_layout.addWidget(progress_bar, 1)  # Stretch factor 1

            usage_widgets[key] = {"label": usage_text, "progress": progress_bar}
            usage_layout.addLayout(row_layout)

        usage_frame.setLayout(usage_layout)

        return {
            "usage_frame": usage_frame,
            "plan_role_label": plan_role_label,
            "usage_widgets": usage_widgets,
        }

    def _create_project_section(self):
        """Create project list section"""
        # Project list
        project_list = QListWidget()
        project_list.setSpacing(6)
        project_list.setStyleSheet(
            """
            QListWidget {
                border-radius: 6px;
                padding: 8px;
            }
            QListWidget::item {
                border-radius: 6px;
                margin: 3px;
            }
            QListWidget::item:selected {
                background-color: rgba(255, 255, 255, 0.1);
                border: 1px solid #1976d2;
            }
            QListWidget::item:hover {
                background-color: rgba(255, 255, 255, 0.2);
            }
        """
        )
        project_list.itemSelectionChanged.connect(self.on_project_selected)
        return {"project_list": project_list}

    def _create_button_panel(self):
        """Create bottom button panel"""
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)

        # New Project button on the left
        new_project_button = QPushButton(self.tr("+ New Project"))
        new_project_button.clicked.connect(self.create_new_project)
        button_layout.addWidget(new_project_button)

        button_layout.addStretch()

        # Cancel and OK buttons
        cancel_btn = QPushButton(self.tr("Cancel"))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        ok_btn = QPushButton(self.tr("OK"))
        ok_btn.setEnabled(False)
        ok_btn.clicked.connect(self.accept)
        button_layout.addWidget(ok_btn)

        return {
            "layout": button_layout,
            "ok_btn": ok_btn,
            "new_project_btn": new_project_button,
        }

    def load_organizations(self):
        """Load organizations into the combo box"""
        self.account_org_panel["org_combo"].clear()
        organizations = api.organization.get_organizations()
        for org in organizations:
            self.account_org_panel["org_combo"].addItem(org.name, org)

    def on_organization_changed(self, index):
        """Handle organization selection change"""
        # 組織の選択が変更されたら、プロジェクト選択状態を初期化
        self.project_section["project_list"].setCurrentItem(None)
        org_data = self.account_org_panel["org_combo"].itemData(index)
        if org_data:
            self.load_organization_detail(org_data)
            self.load_projects(org_data)

    def load_organization_detail(self, org: api.organization.Organization):
        """Load and display organization detail including usage"""
        try:
            # Store current organization ID
            self.current_org_id = org.id
            # Fetch organization details
            org_detail = api.organization.get_organization(org.id)
        except Exception as e:
            msg = self.tr("Failed to load organization details. {}").format(
                format_api_error(e)
            )
            QgsMessageLog.logMessage(msg, LOG_CATEGORY, Qgis.Warning)
            QMessageBox.critical(self, self.tr("Error"), msg)
            return

        # Update usage display
        self.update_usage_display(org_detail)

        if org_detail.role == "OWNER":
            self.button_panel["new_project_btn"].setEnabled(True)
        else:
            self.button_panel["new_project_btn"].setEnabled(False)

    def load_user_info(self):
        """Load current user information"""
        user = api.user.get_me()

        self.account_org_panel["user_name_label"].setText(user.name)

        # Set avatar image if available
        if user.avatarImage:
            avatar_url = api.config.get_api_config().SERVER_URL + user.avatarImage
            self.account_org_panel["avatar_label"].load(avatar_url)
        # if no image, set avatar initial
        elif len(user.name) > 0:
            initial = user.name[0].upper()
            self.account_org_panel["avatar_label"].setText(initial)

    def toggle_details(self):
        """Toggle visibility of usage details panel"""
        self.details_visible = not self.details_visible
        self.org_details_panel["usage_frame"].setVisible(self.details_visible)

        if self.details_visible:
            self.account_org_panel["details_toggle"].setText(
                self.tr("<a href='#'>Hide details &#9650;</a>")
            )
        else:
            self.account_org_panel["details_toggle"].setText(
                self.tr("<a href='#'>Show details &#9660;</a>")
            )

    def open_organization_settings(self):
        """Open organization settings in web browser"""
        if not self.current_org_id:
            return

        settings_url = f"{api.config.get_api_config().SERVER_URL}/organization/{self.current_org_id}/setting"

        try:
            webbrowser.open(settings_url)
        except Exception as e:
            msg = self.tr("Error opening web browser: {}").format(format_api_error(e))
            QgsMessageLog.logMessage(msg, LOG_CATEGORY, Qgis.Critical)
            QMessageBox.critical(self, self.tr("Error"), msg)

    def update_usage_display(self, org_detail: api.organization.OrganizationDetail):
        """Update the usage display with organization details"""
        # Update plan label
        self.org_details_panel["plan_role_label"].setText(
            self.tr("<div><span>{} Plan</span><br /><span>{}</span></div>").format(
                org_detail.subscriptionPlan.capitalize(), org_detail.role.capitalize()
            )
        )

        # Get plan limits from API
        try:
            plan_type = org_detail.subscriptionPlan
            plan_limits = api.plan.get_plan_limits(plan_type)
        except Exception as e:
            msg = self.tr("Failed to retrieve plan limits: {}").format(
                format_api_error(e)
            )
            QgsMessageLog.logMessage(msg, LOG_CATEGORY, Qgis.Critical)
            QMessageBox.warning(self, self.tr("Warning"), msg)

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
        if "storage" in self.org_details_panel["usage_widgets"]:
            used = org_detail.usage.usedStorageUnits
            total = org_detail.storageUnits
            # Format storage units with appropriate suffix
            self.org_details_panel["usage_widgets"]["storage"]["label"].setText(
                f"{used:.2f}SU / {total:.0f}SU"
            )
            if total > 0:
                self.org_details_panel["usage_widgets"]["storage"][
                    "progress"
                ].setMaximum(total)
                self.org_details_panel["usage_widgets"]["storage"]["progress"].setValue(
                    math.ceil(used)
                )
                self._set_progress_color(
                    self.org_details_panel["usage_widgets"]["storage"]["progress"],
                    used,
                    total,
                )

        # Role is now shown in the header, so no need to update separate labels

    def _update_usage_widget(self, key: str, used: int, limit: int):
        """Update a single usage widget with values and colors"""
        if key not in self.org_details_panel["usage_widgets"]:
            return

        widgets = self.org_details_panel["usage_widgets"][key]
        widgets["label"].setText(f"{used} / {limit}")
        widgets["progress"].setMaximum(limit)
        widgets["progress"].setValue(min(limit, used))
        self._set_progress_color(widgets["progress"], used, limit)

    def _set_progress_color(self, progress_bar: QProgressBar, used: int, limit: int):
        """Set progress bar color based on usage percentage"""
        percentage = (used / limit * 100) if limit > 0 else 0

        # Determine color based on usage percentage
        color = _get_usage_color(percentage)

        progress_bar.setStyleSheet(
            f"""
            QProgressBar {{
                border: none;
                border-radius: 3px;
                background-color: #e0e0e0;
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 3px;
            }}
        """
        )

    def load_projects(self, org: api.organization.Organization):
        """Load projects for the selected organization"""
        try:
            self.project_section["project_list"].clear()
            projects = api.project.get_projects_by_organization(org.id)

            for project_item in projects:
                # Create custom widget
                item_widget = ProjectItemWidget(project_item, self.current_org_id, self)

                # Create list item
                list_item = QListWidgetItem(self.project_section["project_list"])
                list_item.setSizeHint(item_widget.sizeHint())
                list_item.setData(QT_USER_ROLE, project_item)

                # Set the custom widget
                self.project_section["project_list"].addItem(list_item)
                self.project_section["project_list"].setItemWidget(
                    list_item, item_widget
                )

        except Exception as e:
            msg = self.tr("Failed to load projects: {}").format(format_api_error(e))
            QgsMessageLog.logMessage(msg, LOG_CATEGORY, Qgis.Critical)
            QMessageBox.critical(self, self.tr("Error"), msg)

    def handle_project_deleted(self):
        """Handle cleanup after a project has been deleted"""
        self.project_section["project_list"].setCurrentItem(None)

    def on_project_selected(self):
        """Handle project selection"""
        current_item = self.project_section["project_list"].currentItem()
        self.selected_project = (
            current_item.data(QT_USER_ROLE) if current_item else None
        )
        self.button_panel["ok_btn"].setEnabled(bool(self.selected_project))

    def get_selected_organization(self) -> Optional[api.organization.Organization]:
        """Get the selected organization"""
        return (
            self.account_org_panel["org_combo"].currentData()
            if self.account_org_panel["org_combo"].currentIndex() >= 0
            else None
        )

    def accept(self):
        """Handle dialog acceptance"""
        org = self.get_selected_organization()
        if org and self.selected_project:
            store_setting("selected_organization_id", org.id)
            store_setting("selected_project_id", self.selected_project.id)
        super().accept()

    def load_saved_selection(self):
        """Load previously saved selection"""
        org_id = get_settings().selected_organization_id
        project_id = get_settings().selected_project_id
        if not org_id or not project_id:
            return
        self._select_organization_by_id(org_id)
        self._select_project_by_id(project_id)

    def create_new_project(self):
        """Create a new project in the selected organization"""
        if not (org := self.get_selected_organization()):
            QMessageBox.warning(
                self,
                self.tr("No Organization Selected"),
                self.tr("Please select an organization first."),
            )
            return

        project_name, ok = QInputDialog.getText(
            self,
            self.tr("New Project"),
            self.tr("Enter a name for your new project in '{}':").format(org.name),
        )
        if not ok or not project_name:
            return

        try:
            new_project = api.project.create_project(
                organization_id=org.id, name=project_name, description=""
            )
            QgsMessageLog.logMessage(
                self.tr("Project '{}' created successfully").format(project_name),
                LOG_CATEGORY,
                Qgis.Info,
            )
            # refresh project list and select the new project
            self.load_organization_detail(org)
            self.load_projects(org)
            self._select_project_by_id(new_project.id)

            QMessageBox.information(
                self,
                self.tr("Project Created"),
                self.tr("Project '{}' has been created successfully.").format(
                    project_name
                ),
            )
        except Exception as e:
            msg = self.tr("Failed to create project: {}").format(format_api_error(e))
            QgsMessageLog.logMessage(msg, LOG_CATEGORY, Qgis.Critical)
            QMessageBox.critical(self, self.tr("Error"), msg)

    def _select_organization_by_id(self, org_id: str):
        """Select organization by ID in combo box"""
        for i in range(self.account_org_panel["org_combo"].count()):
            if (
                org := self.account_org_panel["org_combo"].itemData(i)
            ) and org.id == org_id:
                self.account_org_panel["org_combo"].setCurrentIndex(i)
                break

    def _select_project_by_id(self, project_id: str):
        """Select project by ID in list"""
        for i in range(self.project_section["project_list"].count()):
            item = self.project_section["project_list"].item(i)
            if (
                item
                and (project := item.data(QT_USER_ROLE))
                and project.id == project_id
            ):
                self.project_section["project_list"].setCurrentItem(item)
                break


class ProjectItemWidget(QWidget):
    """Custom widget for displaying project information in a card-like layout"""

    def __init__(
        self,
        project: api.project.ProjectsInOrganization,
        organization_id: str,
        parent_dialog: ProjectSelectDialog,
    ):
        super().__init__()
        self.project = project
        self.organization_id = organization_id
        self.parent_dialog = parent_dialog
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.setup_ui()

    def tr(self, message):
        """Get the translation for a string using Qt translation API"""
        return QCoreApplication.translate("ProjectItemWidget", message)

    def setup_ui(self):
        """Set up the project item UI"""
        main_layout = QHBoxLayout()
        main_layout.setSpacing(12)

        # Thumbnail placeholder - map preview style
        thumbnail_label = RemoteImageLabel(size=(100, 60))
        # load thumbnail image if available
        thumbnail_label.load(f"{self.project.thumbnailImageUrl}&w=320&h=180")
        thumbnail_label.setStyleSheet(
            """
            QLabel {
                border: 1px solid #e0e0e0;
                border-radius: 4px;
            }
        """
        )
        main_layout.addWidget(thumbnail_label)

        # Project info layout
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        # Project name
        name_label = QLabel(self.project.name)
        info_layout.addWidget(name_label)
        # Last updated with icon
        updated_hlayout = QHBoxLayout()
        updated_icon_label = QLabel()
        updated_icon_label.setPixmap(RELOAD_ICON.pixmap(16, 16))
        updated_hlayout.addWidget(updated_icon_label)
        updated_label = QLabel(self._format_relative_date(self.project.updatedAt))
        updated_hlayout.addWidget(updated_label)
        info_layout.addLayout(updated_hlayout)

        main_layout.addLayout(info_layout)
        main_layout.addStretch()

        # Right side icons and size
        right_layout = QVBoxLayout()
        right_layout.setAlignment(Qt.AlignRight | Qt.AlignTop)

        # Icons row
        icons_layout = QHBoxLayout()
        icons_layout.setSpacing(4)

        # Vector icon with count (using emoji for simplicity)
        vector_hlayout = QHBoxLayout()
        vector_icon_label = QLabel()
        vector_icon_label.setPixmap(VECTOR_ICON.pixmap(16, 16))
        vector_hlayout.addWidget(vector_icon_label)
        vector_label = QLabel(str(self.project.vectorCount))
        vector_hlayout.addWidget(vector_label)
        icons_layout.addLayout(vector_hlayout)

        # Maps icon with count
        maps_hlayout = QHBoxLayout()
        maps_icon_label = QLabel()
        maps_icon_label.setPixmap(MAP_ICON.pixmap(16, 16))
        maps_hlayout.addWidget(maps_icon_label)
        maps_label = QLabel(str(self.project.mapCount))
        maps_hlayout.addWidget(maps_label)
        icons_layout.addLayout(maps_hlayout)

        right_layout.addLayout(icons_layout)
        main_layout.addLayout(right_layout)

        self.setLayout(main_layout)

    def _format_date(self, date_string: str) -> str:
        """Format ISO date string to readable format"""
        if not date_string:
            return "Never"
        try:
            dt = datetime.fromisoformat(date_string.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, AttributeError):
            return date_string

    def _format_relative_date(self, date_string: str) -> str:
        """Format date as relative time (e.g., '1 day ago')"""
        if not date_string:
            return "Never"
        try:
            dt = datetime.fromisoformat(date_string.replace("Z", "+00:00"))
            now = datetime.now(dt.tzinfo)
            delta = now - dt

            if delta.days == 0:
                if delta.seconds < 3600:
                    return self.tr("{} minutes ago").format(delta.seconds // 60)
                else:
                    return self.tr("{} hours ago").format(delta.seconds // 3600)
            elif delta.days == 1:
                return self.tr("1 day ago")
            elif delta.days < 30:
                return self.tr("{} days ago").format(delta.days)
            elif delta.days < 365:
                return self.tr("{} months ago").format(delta.days // 30)
            else:
                return self.tr("{} years ago").format(delta.days // 365)
        except (ValueError, AttributeError):
            return date_string

    def show_context_menu(self, position):
        """Show context menu for project item"""
        menu = QMenu(self)

        # Open in Web action
        open_web_action = menu.addAction(self.tr("Open in Web App"))
        open_web_action.triggered.connect(self.open_in_web)

        # Edit action
        edit_action = menu.addAction(self.tr("Edit Project"))
        edit_action.triggered.connect(self.edit_project)

        menu.addSeparator()

        # Delete action
        delete_action = menu.addAction(self.tr("Delete Project"))
        delete_action.triggered.connect(self.delete_project)

        menu.exec_(self.mapToGlobal(position))

    def open_in_web(self):
        """Open project in web browser"""
        if not self.project:
            return

        config = api.config.get_api_config()
        base_url = config.SERVER_URL.rstrip("/")
        project_url = (
            f"{base_url}/organization/{self.organization_id}/project/{self.project.id}"
        )

        try:
            webbrowser.open(project_url)
        except Exception as e:
            QgsMessageLog.logMessage(
                self.tr("Error opening web browser: {}").format(format_api_error(e)),
                LOG_CATEGORY,
                Qgis.Critical,
            )

    def delete_project(self):
        """Delete project with confirmation"""
        if not self.project or not self.parent_dialog:
            return

        # Show confirmation dialog
        reply = QMessageBox.question(
            self.parent_dialog,
            self.tr("Delete Project"),
            self.tr(
                "Are you sure you want to delete project '{}'?\n"
                "This action can't be undone."
            ).format(self.project.name),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            try:
                # Call API to delete project
                api.project.delete_project(self.project.id)

                QgsMessageLog.logMessage(
                    self.tr("Project '{}' deleted successfully.").format(
                        self.project.name
                    ),
                    LOG_CATEGORY,
                    Qgis.Info,
                )

                self.parent_dialog.handle_project_deleted()
                # Refresh the project list
                org = self.parent_dialog.get_selected_organization()
                if org:
                    self.parent_dialog.load_organization_detail(org)
                    self.parent_dialog.load_projects(org)

                QMessageBox.information(
                    self.parent_dialog,
                    self.tr("Project Deleted"),
                    self.tr("Project '{}' has been deleted successfully.").format(
                        self.project.name
                    ),
                )
            except Exception as e:
                QgsMessageLog.logMessage(
                    self.tr("Failed to delete project: {}").format(format_api_error(e)),
                    LOG_CATEGORY,
                    Qgis.Critical,
                )
                QMessageBox.critical(
                    self.parent_dialog,
                    self.tr("Error"),
                    self.tr("Failed to delete project: {}").format(format_api_error(e)),
                )

    def edit_project(self):
        """Edit project metadata"""
        if not self.project or not self.parent_dialog:
            return

        # Show input dialog with current project name
        new_name, ok = QInputDialog.getText(
            self.parent_dialog,
            self.tr("Edit Project"),
            self.tr("Project name:"),
            text=self.project.name,
        )

        if ok and new_name and new_name != self.project.name:
            try:
                # Call API to update project
                updated_project = api.project.update_project(
                    project_id=self.project.id, name=new_name, description=""
                )

                QgsMessageLog.logMessage(
                    self.tr("Project '{}' renamed to '{}' successfully").format(
                        self.project.name, new_name
                    ),
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
                    self.tr("Project Updated"),
                    self.tr("Project has been renamed to '{}' successfully.").format(
                        new_name
                    ),
                )
            except Exception as e:
                QgsMessageLog.logMessage(
                    self.tr("Failed to update project: {}").format(format_api_error(e)),
                    LOG_CATEGORY,
                    Qgis.Critical,
                )
                QMessageBox.critical(
                    self.parent_dialog,
                    self.tr("Error"),
                    self.tr("Failed to update project: {}").format(format_api_error(e)),
                )
