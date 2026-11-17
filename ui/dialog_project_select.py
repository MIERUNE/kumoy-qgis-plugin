import math
import re
import webbrowser
from datetime import datetime
from typing import List, Optional, Set

from qgis.core import QgsProject
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
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from qgis.utils import iface

from .. import i18n
from ..kumoy import api, settings_manager
from ..kumoy.api.models import (
    OrganizationDetail,
    OrganizationWithRole,
    ProjectInOrganization,
    TeamWithRole,
    is_editor,
)
from ..kumoy.constants import DOCUMENTATION_URL
from ..kumoy.tasks import run_task
from ..pyqt_version import (
    Q_LIST_VIEW_RESIZE_MODE,
    QT_ALIGN,
    QT_CUSTOM_CONTEXT_MENU,
    QT_LINEEDIT_ACTION_POSITION,
    QT_NO_ITEM_FLAGS,
    QT_TEXT_FORMAT_PLAIN,
    QT_USER_ROLE,
    exec_dialog,
    exec_menu,
)
from .dialog_project_edit import ProjectEditDialog
from .error_handler import handle_api_error, push_success, refresh_kumoy_browser
from .icons import MAP_ICON, RASTER_ICON, RELOAD_ICON, SEARCH_ICON, VECTOR_ICON
from .remote_image_label import RemoteImageLabel
from .utils import confirm, kumoy_map_open

# The organization shown when the dialog was last used
LAST_ORGANIZATION_KEY = "last_organization_id"


def open_project_dialog() -> None:
    """Let the user pick a project, then switch the Browser to it."""
    dialog = ProjectSelectDialog()
    # exec() returns 1 when accepted (a plain int under PyQt6)
    if not exec_dialog(dialog) or dialog.selected_project is None:
        return
    project_id = dialog.selected_project.id
    if project_id != settings_manager.selected_project_id() and kumoy_map_open():
        # The open map belongs to the previous project
        if QgsProject.instance().isDirty() and not confirm(
            None,
            i18n.tr("Change Project"),
            i18n.tr("Switching projects will discard the current map state. Continue?"),
        ):
            return
        QgsProject.instance().clear()
        if iface is not None:
            iface.messageBar().pushInfo(
                i18n.tr("Project Changed"),
                i18n.tr(
                    "Your QGIS project was cleared because the active project changed."
                ),
            )
    settings_manager.select_project(dialog.selected_organization_id, project_id)
    # Always rebuild: after logging in again the same project needs it too
    refresh_kumoy_browser()


# subscriptionPlan is a system identifier that differs from the plan name
# shown to users, so it must never be displayed as-is.
_PLAN_DISPLAY_NAMES = {
    "FREE": "Community",
    "PRO": "Pro",
    "BUSINESS": "Business",
    "TEAM": "Corporate",
    "CUSTOM": "Enterprise",
}


def _plan_display_name(subscription_plan: str) -> str:
    return _PLAN_DISPLAY_NAMES.get(
        subscription_plan.upper(), subscription_plan.capitalize()
    )


def _get_usage_color(percentage: float) -> str:
    """Get color based on usage percentage"""
    # Color thresholds
    if percentage >= 80:
        return "#f44336"  # Red
    elif percentage >= 75:
        return "#ffa726"  # Orange
    return "#8bc34a"  # Green


def _lighten(hex_color: str, ratio: float = 0.2) -> str:
    """Blend a #rrggbb color toward white"""
    channels = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    blended = (round(c + (255 - c) * ratio) for c in channels)
    return "#" + "".join(f"{c:02x}" for c in blended)


def _chunk_fill(color: str, used: float, limit: int, pending: int) -> str:
    """Fill for the progress chunk, with pending seats as a lighter tail.

    Invites already consume a seat but are not active members yet, so the web
    app paints that part of the gauge in a lighter shade. Qt has no two-segment
    progress bar, so split the chunk itself with a hard gradient stop.
    """
    shown = min(used, limit)
    if pending <= 0 or shown <= 0:
        return color

    # The gradient spans the chunk, not the whole bar, so the boundary is
    # relative to what is actually drawn (clamped when usage exceeds the limit).
    boundary = max(0.0, min(1.0, (shown - pending) / shown))
    light = _lighten(color)
    return (
        "qlineargradient(x1:0, y1:0, x2:1, y2:0, "
        f"stop:0 {color}, stop:{boundary:.4f} {color}, "
        f"stop:{min(1.0, boundary + 0.0001):.4f} {light}, stop:1 {light})"
    )


def _scheduled_deletion_message(iso_string: str) -> str:
    """Build the deletion notice from an ISO 8601 timestamp.

    The date format lives in the translated sentence itself: each language
    arranges the {year}/{month}/{day} placeholders in its own way (English
    uses an unambiguous ISO date, Japanese uses 年月日).
    """
    try:
        dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return i18n.tr("This organization is scheduled for deletion.")
    return i18n.tr(
        "This organization is scheduled for deletion on {year}-{month:02d}-{day:02d}."
    ).format(year=dt.year, month=dt.month, day=dt.day)


class ProjectSelectDialog(QDialog):
    """Pick a project of one of the user's organizations.

    Shows immediately; the user, the organizations and then the selected
    organization's projects/teams/usage load in the background. Results of
    an organization the user already left are dropped (see _org_seq).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.tr("Select Project"))
        self.resize(550, 600)
        self.setMinimumWidth(500)
        self.selected_project: Optional[ProjectInOrganization] = None
        self.selected_organization_id = ""
        self.current_org_id: Optional[str] = None
        self.details_visible = False
        self.myteams: List[TeamWithRole] = []
        self.admin_team_ids: Set[str] = set()
        # Bumped per organization load; stale results are ignored
        self._org_seq = 0
        # Project to select once the list arrives
        self._wanted_project_id = settings_manager.selected_project_id()
        self.setup_ui()
        self.project_section["project_list"].itemDoubleClicked.connect(
            self._on_project_double_clicked
        )
        self.load_user_info()
        self.load_organizations()

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
        account_label = QLabel(i18n.tr("Account"))
        account_org_layout.addWidget(account_label, 0, 0, 1, 2)
        # Avatar and user name
        avatar_name_layout = QHBoxLayout()
        avatar_label = RemoteImageLabel(size=(32, 32))
        avatar_label.set_circular_mask()
        avatar_label.setAlignment(QT_ALIGN.AlignCenter)

        avatar_name_layout.addWidget(avatar_label)

        # User name label
        user_name_label = QLabel(i18n.tr("Loading..."))
        avatar_name_layout.addWidget(user_name_label)
        account_org_layout.addLayout(avatar_name_layout, 1, 0, 1, 2)
        # Organization label
        org_label = QLabel(i18n.tr("Organization"))
        account_org_layout.addWidget(org_label, 0, 2)
        # "show details" link
        details_toggle = QLabel(i18n.tr("<a href='#'>Show details &#9660;</a>"))
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

        refresh_button = QPushButton(RELOAD_ICON, "")
        refresh_button.setToolTip(i18n.tr("Refresh"))
        refresh_button.setFixedSize(32, 32)
        refresh_button.clicked.connect(self.reload_dialog)

        org_row_layout = QHBoxLayout()
        org_row_layout.setSpacing(4)
        org_row_layout.addWidget(org_combo)
        org_row_layout.addWidget(refresh_button)
        account_org_layout.addLayout(org_row_layout, 1, 2, 1, 2)

        return {
            "layout": account_org_layout,
            "avatar_label": avatar_label,
            "user_name_label": user_name_label,
            "org_combo": org_combo,
            "details_toggle": details_toggle,
            "refresh_btn": refresh_button,
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
        org_settings_button = QPushButton(i18n.tr("Organization Settings"))
        org_settings_button.clicked.connect(self.open_organization_settings)
        header_layout.addWidget(org_settings_button)

        usage_layout.addLayout(header_layout)

        # usage
        usage_widgets = {}
        resources = [
            ("projects", "Projects"),
            ("maps", "Maps"),
            ("vectors", "Vectors"),
            ("rasters", "Rasters"),
            ("members", "Members"),
            ("editors", "Editors"),
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
        search_input.setPlaceholderText(i18n.tr("Search..."))
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
        project_list.setResizeMode(Q_LIST_VIEW_RESIZE_MODE.Adjust)
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

        # Help button
        help_btn = QPushButton(i18n.tr("Help"))
        help_btn.setAutoDefault(False)
        help_btn.clicked.connect(lambda: webbrowser.open(DOCUMENTATION_URL))
        button_layout.addWidget(help_btn)

        # New Project button on the left
        new_project_button = QPushButton(i18n.tr("+ New Project"))
        new_project_button.clicked.connect(self.create_new_project)
        button_layout.addWidget(new_project_button)

        button_layout.addStretch()

        # Cancel and OK buttons
        cancel_btn = QPushButton(i18n.tr("Cancel"))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        ok_btn = QPushButton(i18n.tr("OK"))
        ok_btn.setEnabled(False)
        ok_btn.clicked.connect(self.accept)
        button_layout.addWidget(ok_btn)

        return {
            "layout": button_layout,
            "ok_btn": ok_btn,
            "new_project_btn": new_project_button,
        }

    # --- Loading ---------------------------------------------------------

    def _set_list_message(self, text: str, button: Optional[QPushButton] = None):
        """Replace the project list with a non-selectable message."""
        project_list = self._clear_list()
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setAlignment(QT_ALIGN.AlignCenter)
        layout.addWidget(label)
        if button is not None:
            layout.addWidget(button, alignment=QT_ALIGN.AlignCenter)
        item = QListWidgetItem(project_list)
        item.setFlags(QT_NO_ITEM_FLAGS)
        item.setSizeHint(widget.sizeHint())
        project_list.setItemWidget(item, widget)

    def load_user_info(self):
        def on_success(user: api.models.User) -> None:
            name = user.name or user.email or ""
            self.account_org_panel["user_name_label"].setText(name)
            if user.avatarImage:
                self.account_org_panel["avatar_label"].load(
                    api.user.resolve_avatar_url(user.avatarImage)
                )
            elif name:
                self.account_org_panel["avatar_label"].setText(name[0].upper())

        def on_error(e: Exception) -> None:
            # The organization load reports the same problem; stay quiet here
            self.account_org_panel["user_name_label"].setText("")

        run_task(
            i18n.tr("Loading Kumoy account"),
            lambda t: api.user.get_me(),
            on_success,
            on_error,
        )

    def load_organizations(self):
        org_combo = self.account_org_panel["org_combo"]
        org_combo.blockSignals(True)
        org_combo.clear()
        org_combo.addItem(i18n.tr("Loading..."), None)
        org_combo.blockSignals(False)
        org_combo.setEnabled(False)
        self._org_seq += 1  # results of a previous organization are stale now
        self._clear_org_details()
        self._set_list_message(i18n.tr("Loading..."))
        run_task(
            i18n.tr("Loading Kumoy organizations"),
            lambda t: api.organization.get_organizations(),
            self._on_organizations,
            self._on_organizations_error,
        )

    def _on_organizations_error(self, e: Exception) -> None:
        self.account_org_panel["org_combo"].clear()
        self._set_list_message(i18n.tr("Could not load your organizations."))
        handle_api_error(e, parent=self, title=i18n.tr("Failed to load organizations"))

    def _on_organizations(self, organizations: List[OrganizationWithRole]) -> None:
        org_combo = self.account_org_panel["org_combo"]
        org_combo.blockSignals(True)
        org_combo.clear()
        for org in organizations:
            org_combo.addItem(org.name, org)
        preferred = (
            self.current_org_id
            or settings_manager.get(LAST_ORGANIZATION_KEY)
            or settings_manager.selected_organization_id()
        )
        index = next((i for i, o in enumerate(organizations) if o.id == preferred), 0)
        org_combo.setCurrentIndex(index)
        org_combo.blockSignals(False)
        org_combo.setEnabled(bool(organizations))

        if not organizations:
            self._handle_no_organization()
            return
        # Signals were blocked while filling, so this is the only load
        self.on_organization_changed(index)

    def _handle_no_organization(self):
        create_org_btn = QPushButton(i18n.tr("Create Organization"))
        create_org_url = f"{api.client.server_url()}/organization"
        create_org_btn.clicked.connect(lambda: webbrowser.open(create_org_url))
        self._set_list_message(
            i18n.tr("No organization available. Please create one to get started."),
            create_org_btn,
        )
        self.org_details_panel["plan_role_label"].setText(
            i18n.tr("<div><span>No organization available</span></div>")
        )
        self._clear_org_details()

    def _clear_org_details(self):
        """Reset usage widgets and disable organization-scoped actions"""
        for widgets in self.org_details_panel["usage_widgets"].values():
            widgets["label"].setText("")
            widgets["progress"].setMaximum(1)
            widgets["progress"].setValue(0)
            self._set_progress_color(widgets["progress"], 0, 1)
        self.button_panel["new_project_btn"].setEnabled(False)
        self.org_details_panel["org_settings_button"].setEnabled(False)

    def on_organization_changed(self, index):
        self.project_section["search_input"].clear()
        self.selected_project = None
        self.button_panel["ok_btn"].setEnabled(False)
        org = self.account_org_panel["org_combo"].itemData(index)
        if not org:
            return
        self.current_org_id = org.id
        settings_manager.store(LAST_ORGANIZATION_KEY, org.id)
        self._org_seq += 1
        self.myteams = []
        self.admin_team_ids = set()
        self._update_team_filter_combo()
        self._clear_org_details()
        if org.scheduledDeletionAt:
            # Deactivated on the web app: its detail/project APIs answer not
            # found, so show a notice instead of the project list
            self._show_scheduled_deletion_notice(org)
            return
        self.button_panel["new_project_btn"].setVisible(False)
        self._set_list_message(i18n.tr("Loading..."))
        self._load_organization(org)

    def _show_scheduled_deletion_notice(self, org: OrganizationWithRole):
        self.button_panel["new_project_btn"].setVisible(False)
        self._set_list_message(_scheduled_deletion_message(org.scheduledDeletionAt))
        self.org_details_panel["plan_role_label"].setText(
            i18n.tr("<div><span>Scheduled for deletion</span></div>")
        )

    def _load_organization(self, org: OrganizationWithRole) -> None:
        """Projects, teams and usage of `org` in one background task."""
        seq = self._org_seq
        org_id = org.id

        def work(task):
            projects = api.organization.get_projects(org_id)
            teams = api.organization.get_my_teams(org_id)
            try:
                detail = api.organization.get_organization(org_id)
            except Exception:
                detail = None  # only the usage panel needs it
            return projects, teams, detail

        def on_success(result) -> None:
            if seq != self._org_seq:
                return
            projects, teams, detail = result
            self.myteams = teams
            self.admin_team_ids = {t.id for t in teams if is_editor(t.role)}
            has_admin = bool(self.admin_team_ids)
            self.button_panel["new_project_btn"].setVisible(has_admin)
            self.button_panel["new_project_btn"].setEnabled(has_admin)
            self._update_team_filter_combo()
            if detail is not None:
                self.update_usage_display(detail)
                self.org_details_panel["org_settings_button"].setEnabled(True)
            self._fill_projects(projects)

        def on_error(e: Exception) -> None:
            if seq != self._org_seq:
                return
            self._set_list_message(i18n.tr("Could not load the projects."))
            handle_api_error(e, parent=self, title=i18n.tr("Failed to load projects"))

        run_task(i18n.tr("Loading Kumoy projects"), work, on_success, on_error)

    def _update_team_filter_combo(self):
        """Rebuild team filter combo from current myteams"""
        combo = self.project_section["team_combo"]
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(i18n.tr("All teams"), None)
        combo.insertSeparator(1)
        for team in self.myteams:
            combo.addItem(team.name, team.id)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _clear_list(self) -> QListWidget:
        project_list = self.project_section["project_list"]
        # clear() reports the selection change while the old current item
        # still exists, which would select a project that is no longer listed
        project_list.blockSignals(True)
        project_list.clear()
        project_list.blockSignals(False)
        self.on_project_selected()
        return project_list

    def _fill_projects(self, projects: List[ProjectInOrganization]) -> None:
        project_list = self._clear_list()
        if not projects:
            self._set_list_message(i18n.tr("No projects in this organization."))
            return
        for project in projects:
            item_widget = ProjectItemWidget(
                project,
                self.current_org_id,
                self,
                project.teamId in self.admin_team_ids,
            )
            list_item = QListWidgetItem(project_list)
            list_item.setSizeHint(item_widget.sizeHint())
            list_item.setData(QT_USER_ROLE, project)
            project_list.setItemWidget(list_item, item_widget)
        self.filter_projects()
        self._select_project_by_id(self._wanted_project_id)

    # --- Interaction -----------------------------------------------------

    def toggle_details(self):
        self.details_visible = not self.details_visible
        self.org_details_panel["usage_frame"].setVisible(self.details_visible)
        self.account_org_panel["details_toggle"].setText(
            i18n.tr("<a href='#'>Hide details &#9650;</a>")
            if self.details_visible
            else i18n.tr("<a href='#'>Show details &#9660;</a>")
        )

    def open_organization_settings(self):
        if self.current_org_id:
            webbrowser.open(
                f"{api.client.server_url()}/organization/{self.current_org_id}/setting"
            )

    def on_project_selected(self):
        current_item = self.project_section["project_list"].currentItem()
        self.selected_project = (
            current_item.data(QT_USER_ROLE) if current_item else None
        )
        self.button_panel["ok_btn"].setEnabled(self.selected_project is not None)

    def _on_project_double_clicked(self, item: QListWidgetItem) -> None:
        if item.data(QT_USER_ROLE) is not None:
            self.project_section["project_list"].setCurrentItem(item)
            self.accept()

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

    def get_selected_organization(self) -> Optional[OrganizationWithRole]:
        return self.account_org_panel["org_combo"].currentData()

    def accept(self):
        org = self.get_selected_organization()
        if org is None or self.selected_project is None:
            return
        self.selected_organization_id = org.id
        super().accept()

    def reload_dialog(self):
        if self.selected_project is not None:
            self._wanted_project_id = self.selected_project.id
        self.load_user_info()
        self.load_organizations()

    def reload_projects(self, select_project_id: Optional[str] = None) -> None:
        """Reload the current organization, e.g. after a change."""
        if select_project_id is not None:
            self._wanted_project_id = select_project_id
        elif self.selected_project is not None:
            self._wanted_project_id = self.selected_project.id
        org = self.get_selected_organization()
        if org is not None:
            self._org_seq += 1
            self._load_organization(org)

    def _select_project_by_id(self, project_id: str):
        project_list = self.project_section["project_list"]
        for i in range(project_list.count()):
            item = project_list.item(i)
            project = item.data(QT_USER_ROLE)
            if project is not None and project.id == project_id:
                project_list.setCurrentItem(item)
                project_list.scrollToItem(item)
                return

    # --- Project create / edit / delete ----------------------------------

    def _set_busy(self, busy: bool) -> None:
        self.button_panel["ok_btn"].setEnabled(
            not busy and self.selected_project is not None
        )
        self.button_panel["new_project_btn"].setEnabled(
            not busy and bool(self.admin_team_ids)
        )
        self.project_section["project_list"].setEnabled(not busy)

    def _run(self, description: str, fn, on_success, error_title: str) -> None:
        """Run a project change with the dialog marked busy meanwhile."""
        self._set_busy(True)

        def done(result) -> None:
            self._set_busy(False)
            on_success(result)

        def failed(e: Exception) -> None:
            self._set_busy(False)
            handle_api_error(e, parent=self, title=error_title)

        run_task(description, lambda t: fn(), done, failed)

    def create_new_project(self):
        org = self.get_selected_organization()
        if org is None:
            return
        admin_teams = [t for t in self.myteams if t.id in self.admin_team_ids]
        dialog = ProjectEditDialog(org.name, admin_teams, self)
        if not exec_dialog(dialog):
            return
        name = dialog.project_name
        description = dialog.project_description
        team_id = dialog.selected_team.id

        def on_success(project) -> None:
            push_success(
                i18n.tr("Project '{}' has been created successfully.").format(name)
            )
            self.reload_projects(project.id)

        self._run(
            i18n.tr("Creating project"),
            lambda: api.project.create_project(team_id, name, description),
            on_success,
            i18n.tr("Failed to create project"),
        )

    def edit_project(self, project: ProjectInOrganization) -> None:
        org = self.get_selected_organization()
        if org is None:
            return
        dialog = ProjectEditDialog(
            org.name,
            [],
            self,
            initial_name=project.name,
            initial_description=project.description or "",
        )
        dialog.setWindowTitle(i18n.tr("Edit Project"))
        if not exec_dialog(dialog):
            return
        name = dialog.project_name
        description = dialog.project_description
        if name == project.name and description == (project.description or ""):
            return

        def on_success(_) -> None:
            push_success(
                i18n.tr("Project '{}' has been updated successfully.").format(name)
            )
            if project.id == settings_manager.selected_project_id():
                refresh_kumoy_browser()  # the Browser root shows the name
            self.reload_projects(project.id)

        self._run(
            i18n.tr("Updating project"),
            lambda: api.project.update_project(
                project.id, name=name, description=description
            ),
            on_success,
            i18n.tr("Failed to update project"),
        )

    def delete_project(self, project: ProjectInOrganization) -> None:
        if not confirm(
            self,
            i18n.tr("Delete Project"),
            i18n.tr(
                "Are you sure you want to delete project '{}'?\n"
                "This action can't be undone."
            ).format(project.name),
        ):
            return

        def on_success(_) -> None:
            push_success(
                i18n.tr("Project '{}' has been deleted successfully.").format(
                    project.name
                )
            )
            if project.id == settings_manager.selected_project_id():
                # The Browser must not keep showing a project that is gone
                settings_manager.clear_selection()
                refresh_kumoy_browser()
            if self._wanted_project_id == project.id:
                self._wanted_project_id = ""
            if (
                self.selected_project is not None
                and self.selected_project.id == project.id
            ):
                self.selected_project = None
            self.reload_projects()

        self._run(
            i18n.tr("Deleting project"),
            lambda: api.project.delete_project(project.id),
            on_success,
            i18n.tr("Failed to delete project"),
        )

    def update_usage_display(self, org_detail: OrganizationDetail):
        """Update the usage display with organization details"""
        # Update plan label
        self.org_details_panel["plan_role_label"].setText(
            i18n.tr("<div><span>{} Plan</span><br /><span>{}</span></div>").format(
                _plan_display_name(org_detail.subscriptionPlan),
                org_detail.role.capitalize(),
            )
        )

        # Define resource mappings: (key, used, limit, pending)
        resource_mappings = [
            (
                "projects",
                org_detail.usage.projects,
                org_detail.planSettings.maxProjects,
                0,
            ),
            (
                "maps",
                org_detail.usage.styledMaps,
                org_detail.planSettings.maxStyledMaps,
                0,
            ),
            (
                "vectors",
                org_detail.usage.vectors,
                org_detail.planSettings.maxVectors,
                0,
            ),
            (
                "rasters",
                org_detail.usage.rasters,
                org_detail.planSettings.maxRasters,
                0,
            ),
            # Pending invites occupy a seat, so count them too. organizationEditors
            # Seats include pending invites.
            # Editors already include them, members don't.
            (
                "members",
                org_detail.usage.organizationMembers
                + org_detail.usage.organizationInvites,
                org_detail.planSettings.maxOrganizationMembers,
                org_detail.usage.organizationInvites,
            ),
            (
                "editors",
                org_detail.usage.organizationEditors,
                org_detail.availableEditors,
                org_detail.usage.organizationEditorInvites,
            ),
        ]

        # Update each resource
        for key, used, limit, pending in resource_mappings:
            self._update_usage_widget(key, used, limit, pending)

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

    def _update_usage_widget(self, key: str, used: int, limit: int, pending: int = 0):
        """Update a single usage widget with values and colors"""
        if key not in self.org_details_panel["usage_widgets"]:
            return

        widgets = self.org_details_panel["usage_widgets"][key]
        widgets["label"].setText(f"{used} / {limit}")
        widgets["progress"].setMaximum(limit)
        widgets["progress"].setValue(min(limit, used))
        self._set_progress_color(widgets["progress"], used, limit, pending)

    def _set_progress_color(
        self, progress_bar: QProgressBar, used: float, limit: int, pending: int = 0
    ):
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
                background-color: {_chunk_fill(color, used, limit, pending)};
                border-radius: 3px;
            }}
        """
        )


class ProjectItemWidget(QWidget):
    """Custom widget for displaying project information in a card-like layout"""

    def __init__(
        self,
        project: ProjectInOrganization,
        organization_id: str,
        parent_dialog: ProjectSelectDialog,
        is_admin: bool,
    ):
        super().__init__()
        self.project = project
        self.organization_id = organization_id
        self.parent_dialog = parent_dialog
        self.is_admin = is_admin
        self.setContextMenuPolicy(QT_CUSTOM_CONTEXT_MENU)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.setup_ui()

    def setup_ui(self):
        """Set up the project item UI"""
        main_layout = QHBoxLayout()
        main_layout.setSpacing(12)

        # Thumbnail placeholder - map preview style
        thumbnail_label = RemoteImageLabel(size=(100, 60))
        # load thumbnail image if available
        if self.project.thumbnailImageUrl:
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

        # Maps icon with count
        maps_hlayout = QHBoxLayout()
        maps_icon_label = QLabel()
        maps_icon_label.setPixmap(MAP_ICON.pixmap(16, 16))
        maps_hlayout.addWidget(maps_icon_label)
        maps_label = QLabel(str(self.project.mapCount))
        maps_hlayout.addWidget(maps_label)
        icons_layout.addLayout(maps_hlayout)

        # Vector icon with count
        vector_hlayout = QHBoxLayout()
        vector_icon_label = QLabel()
        vector_icon_label.setPixmap(VECTOR_ICON.pixmap(16, 16))
        vector_hlayout.addWidget(vector_icon_label)
        vector_label = QLabel(str(self.project.vectorCount))
        vector_hlayout.addWidget(vector_label)
        icons_layout.addLayout(vector_hlayout)

        # Raster icon with count
        raster_hlayout = QHBoxLayout()
        raster_icon_label = QLabel()
        raster_icon_label.setPixmap(RASTER_ICON.pixmap(16, 16))
        raster_hlayout.addWidget(raster_icon_label)
        raster_label = QLabel(str(self.project.rasterCount))
        raster_hlayout.addWidget(raster_label)
        icons_layout.addLayout(raster_hlayout)

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

        if delta.total_seconds() < 60:
            return i18n.tr("Just now")

        if delta.days == 0:
            if delta.seconds < 3600:
                return i18n.tr("{} minutes ago").format(delta.seconds // 60)
            else:
                return i18n.tr("{} hours ago").format(delta.seconds // 3600)
        elif delta.days == 1:
            return i18n.tr("1 day ago")
        elif delta.days < 30:
            return i18n.tr("{} days ago").format(delta.days)
        elif delta.days < 365:
            return i18n.tr("{} months ago").format(delta.days // 30)
        else:
            return i18n.tr("{} years ago").format(delta.days // 365)

    def show_context_menu(self, position):
        menu = QMenu(self)
        open_web_action = menu.addAction(i18n.tr("Open in Web App"))
        open_web_action.triggered.connect(self.open_in_web)
        if self.is_admin:
            edit_action = menu.addAction(i18n.tr("Edit Project"))
            edit_action.triggered.connect(
                lambda: self.parent_dialog.edit_project(self.project)
            )
            menu.addSeparator()
            delete_action = menu.addAction(i18n.tr("Delete Project"))
            delete_action.triggered.connect(
                lambda: self.parent_dialog.delete_project(self.project)
            )
        exec_menu(menu, self.mapToGlobal(position))

    def open_in_web(self):
        webbrowser.open(
            f"{api.client.server_url()}/organization/{self.organization_id}"
            f"/team/{self.project.teamId}/project/{self.project.id}"
        )
