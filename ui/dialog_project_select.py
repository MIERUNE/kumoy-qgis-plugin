import math
import re
import webbrowser
from datetime import datetime
from typing import List, Optional, Set

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..kumoy import api
from ..kumoy.api.error import format_api_error
from ..kumoy.api.team import TeamDetail
from ..kumoy.constants import (
    LOG_CATEGORY,
)
from ..pyqt_version import (
    Q_MESSAGEBOX_STD_BUTTON,
    QDIALOG_CODE,
    QT_ALIGN,
    QT_CUSTOM_CONTEXT_MENU,
    QT_LINEEDIT_ACTION_POSITION,
    QT_NO_ITEM_FLAGS,
    QT_TEXT_FORMAT_PLAIN,
    QT_USER_ROLE,
    exec_dialog,
    exec_menu,
)
from ..settings_manager import get_settings, store_setting
from .dialog_project_edit import ProjectEditDialog
from .icons import MAP_ICON, RELOAD_ICON, SEARCH_ICON, VECTOR_ICON
from .remote_image_label import RemoteImageLabel
from .utils import show_plain_text_message


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
        self.myteams: List[TeamDetail] = []
        self.admin_team_ids: Set[str] = set()
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
        layout.addWidget(self.project_section["project_frame"])

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
        avatar_label.setAlignment(QT_ALIGN.AlignCenter)

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
        details_toggle.setAlignment(QT_ALIGN.AlignRight)
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
            usage_text.setAlignment(QT_ALIGN.AlignRight)
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
            "org_settings_button": org_settings_button,
        }

    def _create_project_section(self):
        """Create project list section with search and team filter"""
        # Container frame
        project_frame = QFrame()
        project_frame.setStyleSheet(
            """
            QFrame {
                border-radius: 6px;
            }
        """
        )
        frame_layout = QVBoxLayout()
        frame_layout.setContentsMargins(8, 8, 8, 8)
        frame_layout.setSpacing(6)

        # Search and team filter
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(8)

        # Search box (left)
        search_input = QLineEdit()
        search_input.setPlaceholderText(self.tr("Search..."))
        search_input.setClearButtonEnabled(True)
        search_input.addAction(SEARCH_ICON, QT_LINEEDIT_ACTION_POSITION.LeadingPosition)
        search_input.setMinimumHeight(32)
        search_input.setStyleSheet(
            """
            QLineEdit {
                border: 1px solid #ced4da;
                padding: 6px 8px;
                border-radius: 4px;
            }
        """
        )
        search_input.textChanged.connect(self.filter_projects)
        filter_layout.addWidget(search_input, 1)

        # Team filter combo (right)
        team_combo = QComboBox()
        team_combo.setMinimumHeight(32)
        team_combo.setStyleSheet(
            """
            QComboBox {
                border: 1px solid #ced4da;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }
        """
        )
        team_combo.currentIndexChanged.connect(self.filter_projects)
        filter_layout.addWidget(team_combo, 1)

        frame_layout.addLayout(filter_layout)

        # Project list
        project_list = QListWidget()
        project_list.setResizeMode(QListWidget.Adjust)
        project_list.setSpacing(6)
        project_list.setStyleSheet(
            """
            QListWidget {
                border: 1px solid #ced4da;
                border-radius: 4px;
                padding: 0px;
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
        frame_layout.addWidget(project_list)

        project_frame.setLayout(frame_layout)
        return {
            "project_frame": project_frame,
            "team_combo": team_combo,
            "search_input": search_input,
            "project_list": project_list,
        }

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

        if not organizations:
            self._handle_no_organization()
            return
        for org in organizations:
            self.account_org_panel["org_combo"].addItem(org.name, org)

    def _handle_no_organization(self):
        """Handle case when no organization is available"""
        # Clear project list
        self.project_section["project_list"].clear()

        # Add message + button inviting to create an organization instead project list
        no_org_widget = QWidget()
        no_org_layout = QVBoxLayout(no_org_widget)
        no_org_layout.setContentsMargins(12, 12, 12, 12)
        no_org_layout.setSpacing(8)

        msg_label = QLabel(
            self.tr("No organization available. Please create one to get started.")
        )
        msg_label.setAlignment(QT_ALIGN.AlignCenter)
        no_org_layout.addWidget(msg_label)

        create_org_btn = QPushButton(self.tr("Create Organization"))
        create_org_url = f"{api.config.get_api_config().SERVER_URL}/organization"
        create_org_btn.clicked.connect(lambda: webbrowser.open(create_org_url))
        no_org_layout.addWidget(create_org_btn, alignment=QT_ALIGN.AlignCenter)

        no_org_item = QListWidgetItem(self.project_section["project_list"])
        no_org_item.setFlags(QT_NO_ITEM_FLAGS)  # Make it non-selectable
        no_org_item.setSizeHint(no_org_widget.sizeHint())
        self.project_section["project_list"].addItem(no_org_item)
        self.project_section["project_list"].setItemWidget(no_org_item, no_org_widget)

        # Clear organization details
        self.org_details_panel["plan_role_label"].setText(
            self.tr("<div><span>No organization available</span></div>")
        )

        keys = ["projects", "maps", "vectors", "members", "storage"]
        for key in keys:
            widgets = self.org_details_panel["usage_widgets"][key]
            widgets["label"].setText("")
            widgets["progress"].setMaximum(1)
            widgets["progress"].setValue(0)
            self._set_progress_color(widgets["progress"], 0, 1)

        self.button_panel["new_project_btn"].setEnabled(False)
        self.org_details_panel["org_settings_button"].setEnabled(False)

    def on_organization_changed(self, index):
        """Reset project selection when organization changes"""
        self.project_section["project_list"].setCurrentItem(None)
        self.project_section["search_input"].clear()
        org_data = self.account_org_panel["org_combo"].itemData(index)
        if org_data:
            self.load_myteams(org_data)
            self.load_organization_detail(org_data)
            self.load_projects(org_data)

    def load_myteams(self, org: api.organization.Organization):
        """Load teams the current user belongs to in the organization"""
        try:
            self.myteams = api.team.get_organization_myteams(org.id)
            self.admin_team_ids = {
                t.id for t in self.myteams if t.role in ("OWNER", "ADMIN")
            }
        except Exception as e:
            self.myteams = []
            self.admin_team_ids = set()
            msg = self.tr("Failed to load teams: {}").format(format_api_error(e))
            QgsMessageLog.logMessage(msg, LOG_CATEGORY, Qgis.Critical)
            QMessageBox.critical(self, self.tr("Error"), msg)

        # Show/hide "New Project" button based on admin teams
        self.button_panel["new_project_btn"].setVisible(bool(self.admin_team_ids))

        # Update team filter combo
        self._update_team_filter_combo()

    def _update_team_filter_combo(self):
        """Rebuild team filter combo from current myteams"""
        combo = self.project_section["team_combo"]
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(self.tr("All teams"), None)
        combo.insertSeparator(1)
        for team in self.myteams:
            combo.addItem(team.name, team.id)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _select_team_filter(self, team_id: str):
        """Set team filter combo to the given team"""
        combo = self.project_section["team_combo"]
        for i in range(combo.count()):
            if combo.itemData(i) == team_id:
                combo.setCurrentIndex(i)
                return

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
        self.org_details_panel["org_settings_button"].setEnabled(True)

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
                defaultStorageUnits=0,
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
            total = org_detail.availableStorageUnits
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

    def _set_progress_color(self, progress_bar: QProgressBar, used: float, limit: int):
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
                item_widget = ProjectItemWidget(
                    project_item, self.current_org_id, self, self.admin_team_ids
                )

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

        self.filter_projects()

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

    def filter_projects(self):
        """Filter project list by name and team"""
        search_text = self.project_section["search_input"].text().lower()
        selected_team_id = self.project_section["team_combo"].currentData()
        project_list = self.project_section["project_list"]
        for i in range(project_list.count()):
            item = project_list.item(i)
            project = item.data(QT_USER_ROLE)
            if project is None:
                continue
            name_match = search_text in project.name.lower()
            team_match = selected_team_id is None or project.teamId == selected_team_id
            item.setHidden(not (name_match and team_match))

        current = project_list.currentItem()
        if current and current.isHidden():
            project_list.setCurrentItem(None)

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

        admin_teams = [t for t in self.myteams if t.id in self.admin_team_ids]
        new_project_dialog = ProjectEditDialog(org.name, admin_teams, self)
        if exec_dialog(new_project_dialog) != QDIALOG_CODE.Accepted:
            return

        project_name = new_project_dialog.project_name
        project_description = new_project_dialog.project_description
        selected_team = new_project_dialog.selected_team

        try:
            new_project = api.project.create_project(
                team_id=selected_team.id,
                name=project_name,
                description=project_description,
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

            show_plain_text_message(
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
        admin_team_ids: Set[str],
    ):
        super().__init__()
        self.project = project
        self.organization_id = organization_id
        self.parent_dialog = parent_dialog
        self.is_admin = project.teamId in admin_team_ids
        self.setContextMenuPolicy(QT_CUSTOM_CONTEXT_MENU)
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
        name_label.setTextFormat(QT_TEXT_FORMAT_PLAIN)
        info_layout.addWidget(name_label)
        # Last updated with icon
        updated_hlayout = QHBoxLayout()
        updated_hlayout.setSpacing(4)
        updated_hlayout.setContentsMargins(0, 0, 0, 0)
        updated_icon_label = QLabel()
        updated_icon_label.setFixedSize(16, 16)
        updated_icon_label.setPixmap(RELOAD_ICON.pixmap(16, 16))
        updated_hlayout.addWidget(updated_icon_label)
        updated_label = QLabel(self._format_relative_date(self.project.updatedAt))
        updated_hlayout.addWidget(updated_label)
        info_layout.addLayout(updated_hlayout)

        main_layout.addLayout(info_layout)
        main_layout.addStretch()

        # Right side icons and size
        right_layout = QVBoxLayout()
        right_layout.setAlignment(QT_ALIGN.AlignRight | QT_ALIGN.AlignTop)

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

    def _format_relative_date(self, date_string: str) -> str:
        """Format date as relative time (e.g., '1 day ago')
        Input: 2026-01-21 07:08:26.970209+00
        Output: "3 days ago"
        """
        # PostgreSQL timestamptz format: YYYY-MM-DD HH:MM:SS[.fractional]+00
        # Pad fractional seconds to 6 digits (Python 3.9 requires 0, 3 or 6)
        normalized = re.sub(
            r"\.(\d+)(?=[+-Z]|$)",
            lambda m: "." + (m.group(1) + "000000")[:6],
            date_string,
        )
        # +00 -> +00:00 for datetime.fromisoformat
        normalized = re.sub(r"([+-]\d{2})$", r"\1:00", normalized)
        normalized = normalized.replace("Z", "+00:00")

        if not re.match(
            r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d{6})?[+-]\d{2}:\d{2}$",
            normalized,
        ):
            return date_string

        dt = datetime.fromisoformat(normalized)
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

    def show_context_menu(self, position):
        """Show context menu for project item"""
        menu = QMenu(self)

        # Open in Web action
        open_web_action = menu.addAction(self.tr("Open in Web App"))
        open_web_action.triggered.connect(self.open_in_web)

        if self.is_admin:
            # Edit action
            edit_action = menu.addAction(self.tr("Edit Project"))
            edit_action.triggered.connect(self.edit_project)

            menu.addSeparator()

            # Delete action
            delete_action = menu.addAction(self.tr("Delete Project"))
            delete_action.triggered.connect(self.delete_project)

        exec_menu(menu, self.mapToGlobal(position))

    def open_in_web(self):
        """Open project in web browser"""
        if not self.project:
            return

        config = api.config.get_api_config()
        base_url = config.SERVER_URL.rstrip("/")
        project_url = f"{base_url}/organization/{self.organization_id}/team/{self.project.teamId}/project/{self.project.id}"

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
        msg_box = QMessageBox(self.parent_dialog)
        msg_box.setWindowTitle(self.tr("Delete Project"))
        msg_box.setText(
            self.tr(
                "Are you sure you want to delete project '{}'?\n"
                "This action can't be undone."
            ).format(self.project.name)
        )
        msg_box.setTextFormat(QT_TEXT_FORMAT_PLAIN)
        msg_box.setStandardButtons(
            Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No
        )
        msg_box.setDefaultButton(Q_MESSAGEBOX_STD_BUTTON.No)
        reply = exec_dialog(msg_box)

        if reply == Q_MESSAGEBOX_STD_BUTTON.Yes:
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

                show_plain_text_message(
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

        # Get organization name for the dialog
        org = self.parent_dialog.get_selected_organization()
        if not org:
            return

        try:
            # Fetch full project details to get the description
            project_detail = api.project.get_project(self.project.id)
        except Exception as e:
            QgsMessageLog.logMessage(
                self.tr("Failed to load project details: {}").format(
                    format_api_error(e)
                ),
                LOG_CATEGORY,
                Qgis.Critical,
            )
            QMessageBox.critical(
                self.parent_dialog,
                self.tr("Error"),
                self.tr("Failed to load project details: {}").format(
                    format_api_error(e)
                ),
            )
            return

        # Show edit dialog with current project data
        edit_dialog = ProjectEditDialog(
            org.name,
            [],
            self.parent_dialog,
            initial_name=project_detail.name,
            initial_description=project_detail.description,
        )
        edit_dialog.setWindowTitle(self.tr("Edit Project"))

        if exec_dialog(edit_dialog) != QDIALOG_CODE.Accepted:
            return

        new_name = edit_dialog.project_name
        new_description = edit_dialog.project_description

        # Check if anything changed
        if (
            new_name == project_detail.name
            and new_description == project_detail.description
        ):
            return

        try:
            # Call API to update project
            updated_project = api.project.update_project(
                project_id=self.project.id, name=new_name, description=new_description
            )

            QgsMessageLog.logMessage(
                self.tr("Project '{}' updated successfully").format(self.project.name),
                LOG_CATEGORY,
                Qgis.Info,
            )

            # Update the current project data
            self.project = updated_project

            # Refresh the project list
            self.parent_dialog.load_projects(org)
            self.parent_dialog._select_project_by_id(self.project.id)

            show_plain_text_message(
                self.parent_dialog,
                self.tr("Project Updated"),
                self.tr("Project '{}' has been updated successfully.").format(new_name),
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
