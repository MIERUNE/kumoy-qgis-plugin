import math
import re
import webbrowser
from datetime import datetime
from typing import List, Optional, Set

from qgis.core import QgsProject
from qgis.PyQt.QtCore import (
    QItemSelectionModel,
    QModelIndex,
    QPersistentModelIndex,
    QRect,
    QRectF,
    QSize,
    QSortFilterProxyModel,
    Qt,
)
from qgis.PyQt.QtGui import (
    QColor,
    QFontMetrics,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListView,
    QMenu,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QToolButton,
    QTreeView,
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
    Team,
    TeamWithRole,
    is_editor,
)
from ..kumoy.constants import DOCUMENTATION_URL
from ..kumoy.tasks import run_task
from ..pyqt_version import (
    Q_LIST_VIEW_RESIZE_MODE,
    Q_PAINTER_RENDER_HINT,
    QT_ALIGN,
    QT_CUSTOM_CONTEXT_MENU,
    QT_LINEEDIT_ACTION_POSITION,
    QT_TEXT_ELIDE_MODE,
    QT_USER_ROLE,
    exec_dialog,
    exec_menu,
)
from .dialog_project_edit import ProjectEditDialog
from .error_handler import handle_api_error, push_success, refresh_kumoy_browser
from .icons import (
    GRID_ICON,
    LIST_ICON,
    MAP_ICON,
    ORGANIZATION_ICON,
    PIN_ICON,
    RASTER_ICON,
    RELOAD_ICON,
    SEARCH_ICON,
    TEAM_ICON,
    VECTOR_ICON,
    badge_pixmap,
)
from .remote_image_label import RemoteImageLabel, cover_image, fetch_image
from .utils import confirm, kumoy_map_open

# The organization shown when the dialog was last used
LAST_ORGANIZATION_KEY = "last_organization_id"
# "grid" or "table", as last chosen
PROJECT_VIEW_KEY = "project_view"

# Columns of the project model. The table shows them all; the grid paints a
# card per row from the project kept in the first column
(
    _COL_NAME,
    _COL_TEAM,
    _COL_UPDATED,
    _COL_CREATED,
    _COL_MAPS,
    _COL_VECTORS,
    _COL_RASTERS,
    _COL_STORAGE,
) = range(8)
# Raw values to sort by: the displayed text ("3 days ago", "12") sorts wrong
_SORT_ROLE = QT_USER_ROLE + 1
_DECORATION_ROLE = Qt.ItemDataRole.DecorationRole
_THUMBNAIL_SIZE = QSize(320, 180)
# The web app's color for a team without a valid one
_DEFAULT_TEAM_COLOR = "3b82f6"


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


def _parse_timestamp(date_string: str) -> Optional[datetime]:
    """Parse the API's timestamps, e.g. 2026-01-21 07:08:26.970209+00."""
    # Pad fractional seconds to 6 digits (Python 3.9 requires 0, 3 or 6)
    normalized = re.sub(
        r"\.(\d+)(?=[+-Z]|$)",
        lambda m: "." + (m.group(1) + "000000")[:6],
        date_string or "",
    )
    # +00 -> +00:00 for datetime.fromisoformat
    normalized = re.sub(r"([+-]\d{2})$", r"\1:00", normalized)
    normalized = normalized.replace("Z", "+00:00")
    if not re.match(
        r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d{6})?[+-]\d{2}:\d{2}$",
        normalized,
    ):
        return None
    return datetime.fromisoformat(normalized)


def _relative_time(dt: datetime) -> str:
    """'3 days ago' and the like."""
    delta = datetime.now(dt.tzinfo) - dt
    if delta.total_seconds() < 60:
        return i18n.tr("Just now")
    if delta.days == 0:
        if delta.seconds < 3600:
            return i18n.tr("{} minutes ago").format(delta.seconds // 60)
        return i18n.tr("{} hours ago").format(delta.seconds // 3600)
    if delta.days == 1:
        return i18n.tr("1 day ago")
    if delta.days < 30:
        return i18n.tr("{} days ago").format(delta.days)
    if delta.days < 365:
        return i18n.tr("{} months ago").format(delta.days // 30)
    return i18n.tr("{} years ago").format(delta.days // 365)


def _team_icon(team: Optional[Team]) -> QIcon:
    """The team's badge in its color, as on the web app."""
    color = ((team.color if team else "") or "").strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", color):
        color = _DEFAULT_TEAM_COLOR
    return QIcon(badge_pixmap(f"#{color}", TEAM_ICON, 32))


def _rounded(img: QImage) -> QPixmap:
    """The image with rounded corners (organization icons)."""
    pixmap = QPixmap(img.size())
    pixmap.fill(QColor(0, 0, 0, 0))
    path = QPainterPath()
    radius = img.width() / 4
    path.addRoundedRect(QRectF(0, 0, img.width(), img.height()), radius, radius)
    painter = QPainter(pixmap)
    painter.setRenderHint(Q_PAINTER_RENDER_HINT.Antialiasing)
    painter.setClipPath(path)
    painter.drawImage(0, 0, img)
    painter.end()
    return pixmap


def _placeholder_thumbnail() -> QIcon:
    pixmap = QPixmap(_THUMBNAIL_SIZE)
    pixmap.fill(QColor(128, 128, 128, 40))
    painter = QPainter(pixmap)
    pin = 48
    PIN_ICON.paint(
        painter,
        QRect(
            (_THUMBNAIL_SIZE.width() - pin) // 2,
            (_THUMBNAIL_SIZE.height() - pin) // 2,
            pin,
            pin,
        ),
    )
    painter.end()
    return QIcon(pixmap)


def _project_row(
    project: ProjectInOrganization, thumbnail: QIcon
) -> List[QStandardItem]:
    """The model row of a project, one item per _COL_* column."""
    team_name = project.team.name if project.team else ""
    updated = _parse_timestamp(project.updatedAt)
    created = _parse_timestamp(project.createdAt)
    cells = [
        (project.name, project.name.casefold()),
        (team_name, team_name.casefold()),
        (
            _relative_time(updated) if updated else project.updatedAt,
            updated.timestamp() if updated else 0.0,
        ),
        (
            created.astimezone().strftime("%Y-%m-%d") if created else project.createdAt,
            created.timestamp() if created else 0.0,
        ),
        (str(project.mapCount), project.mapCount),
        (str(project.vectorCount), project.vectorCount),
        (str(project.rasterCount), project.rasterCount),
        (f"{project.storageUnitsSum:g} SU", project.storageUnitsSum),
    ]
    items = []
    for text, sort_key in cells:
        item = QStandardItem(text)
        item.setData(sort_key, _SORT_ROLE)
        item.setEditable(False)
        items.append(item)
    items[_COL_NAME].setData(project, QT_USER_ROLE)
    items[_COL_NAME].setIcon(thumbnail)
    items[_COL_NAME].setToolTip(project.name)
    if project.team:
        items[_COL_TEAM].setIcon(_team_icon(project.team))
    if updated:
        items[_COL_UPDATED].setToolTip(updated.astimezone().strftime("%Y-%m-%d %H:%M"))
    for column in (_COL_MAPS, _COL_VECTORS, _COL_RASTERS, _COL_STORAGE):
        items[column].setTextAlignment(QT_ALIGN.AlignRight | QT_ALIGN.AlignVCenter)
    return items


class _ProjectFilter(QSortFilterProxyModel):
    """Name search and team filter, shared by the grid and the table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.text = ""
        self.team_id: Optional[str] = None
        self.setSortRole(_SORT_ROLE)

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:  # noqa: N802
        index = self.sourceModel().index(source_row, _COL_NAME, source_parent)
        project = index.data(QT_USER_ROLE)
        return self.text in project.name.lower() and (
            self.team_id is None or project.teamId == self.team_id
        )


class _SmallIconDelegate(QStyledItemDelegate):
    """Team badges at text size: the table's icon size fits thumbnails."""

    def initStyleOption(self, option, index) -> None:  # noqa: N802
        super().initStyleOption(option, index)
        option.decorationSize = QSize(16, 16)


class _ProjectCardDelegate(QStyledItemDelegate):
    """Paints a project as a card like the web app: thumbnail, name, team,
    last update and item counts."""

    # Thumbnails are fetched at 320 px wide; larger cards would blur them
    MAX_WIDTH = 320
    _MARGIN = 4  # around the card
    _PAD = 8  # inside the card

    width = 216  # set by _ProjectGrid from the view's width

    def height(self, metrics: QFontMetrics) -> int:
        inner = self.width - 2 * self._MARGIN
        return inner * 9 // 16 + 3 * (metrics.height() + 4) + 2 * self._PAD

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(self.width, self.height(option.fontMetrics))

    def paint(self, painter: QPainter, option, index) -> None:
        project: ProjectInOrganization = index.data(QT_USER_ROLE)
        palette = option.palette
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        card = QRectF(option.rect).adjusted(
            self._MARGIN, self._MARGIN, -self._MARGIN, -self._MARGIN
        )
        painter.save()
        painter.setRenderHint(Q_PAINTER_RENDER_HINT.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(card, 6, 6)
        painter.fillPath(path, palette.base())
        painter.save()
        painter.setClipPath(path)  # rounds the thumbnail's top corners
        thumbnail = QRect(
            int(card.left()),
            int(card.top()),
            int(card.width()),
            int(card.width()) * 9 // 16,
        )
        icon = index.data(_DECORATION_ROLE)
        if isinstance(icon, QIcon):
            icon.paint(painter, thumbnail)
        painter.restore()

        if selected:
            pen = QPen(palette.highlight().color(), 2)
        else:
            border = palette.text().color()
            border.setAlpha(110 if hovered else 50)
            pen = QPen(border, 1)
        painter.setPen(pen)
        painter.drawPath(path)

        metrics = option.fontMetrics
        line = metrics.height() + 4
        left = int(card.left()) + self._PAD
        width = int(card.width()) - 2 * self._PAD
        top = thumbnail.bottom() + self._PAD
        text_color = palette.text().color()
        secondary = QColor(text_color)
        secondary.setAlpha(160)

        # Name
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(text_color)
        bold = painter.fontMetrics()
        painter.drawText(
            QRect(left, top, width, line),
            QT_ALIGN.AlignLeft | QT_ALIGN.AlignVCenter,
            bold.elidedText(project.name, QT_TEXT_ELIDE_MODE.ElideRight, width),
        )
        font.setBold(False)
        painter.setFont(font)

        # Team
        top += line
        icon_size = metrics.height()
        icon_top = top + (line - icon_size) // 2
        if project.team:
            _team_icon(project.team).paint(
                painter, QRect(left, icon_top, icon_size, icon_size)
            )
            painter.setPen(secondary)
            painter.drawText(
                QRect(left + icon_size + 4, top, width - icon_size - 4, line),
                QT_ALIGN.AlignLeft | QT_ALIGN.AlignVCenter,
                metrics.elidedText(
                    project.team.name,
                    QT_TEXT_ELIDE_MODE.ElideRight,
                    width - icon_size - 4,
                ),
            )

        # Last update, then the counts right-aligned
        top += line
        icon_top = top + (line - icon_size) // 2
        painter.setPen(secondary)
        right = left + width
        for count_icon, count in (
            (RASTER_ICON, project.rasterCount),
            (VECTOR_ICON, project.vectorCount),
            (MAP_ICON, project.mapCount),
        ):
            text = str(count)
            text_width = metrics.horizontalAdvance(text)
            painter.drawText(
                QRect(right - text_width, top, text_width, line),
                QT_ALIGN.AlignRight | QT_ALIGN.AlignVCenter,
                text,
            )
            right -= text_width + 2 + icon_size
            count_icon.paint(painter, QRect(right, icon_top, icon_size, icon_size))
            right -= 8
        updated = _parse_timestamp(project.updatedAt)
        painter.drawText(
            QRect(left, top, right - left, line),
            QT_ALIGN.AlignLeft | QT_ALIGN.AlignVCenter,
            metrics.elidedText(
                _relative_time(updated) if updated else "",
                QT_TEXT_ELIDE_MODE.ElideRight,
                right - left,
            ),
        )
        painter.restore()


class _ProjectGrid(QListView):
    """Cards in three columns that grow with the view up to MAX_WIDTH."""

    COLUMNS = 3

    def __init__(self) -> None:
        super().__init__()
        self._cards = _ProjectCardDelegate(self)
        self.setItemDelegate(self._cards)

    def resizeEvent(self, event) -> None:  # noqa: N802
        # -1: a row that fills the width exactly wraps its last card.
        # Past MAX_WIDTH the cells keep widening (Qt centers the card in its
        # cell), so a fourth column never fits.
        cell = (self.viewport().width() - 1) // self.COLUMNS
        self._cards.width = min(cell, self._cards.MAX_WIDTH)
        self.setGridSize(QSize(cell, self._cards.height(self.fontMetrics())))
        super().resizeEvent(event)


class ProjectSelectDialog(QDialog):
    """Pick a project of one of the user's organizations.

    Shows immediately; the user, the organizations and then the selected
    organization's projects/teams/usage load in the background. Results of
    an organization the user already left are dropped (see _org_seq).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.tr("Select Project"))
        self.resize(760, 640)
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
        self._placeholder_thumbnail = _placeholder_thumbnail()
        self.setup_ui()
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
        org_combo.setIconSize(QSize(20, 20))
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
        """Search, team filter and the projects as a grid or a table"""
        project_frame = QFrame()
        frame_layout = QVBoxLayout()
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(6)

        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(8)

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

        team_combo = QComboBox()
        team_combo.setMinimumHeight(32)
        team_combo.setIconSize(QSize(16, 16))
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

        # Grid / table switch
        view_buttons = QButtonGroup(project_frame)
        for view_id, (icon, tooltip) in enumerate(
            ((GRID_ICON, i18n.tr("Grid")), (LIST_ICON, i18n.tr("Table")))
        ):
            button = QToolButton()
            button.setIcon(icon)
            button.setToolTip(tooltip)
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setFixedSize(32, 32)
            view_buttons.addButton(button, view_id)
            filter_layout.addWidget(button)
        frame_layout.addLayout(filter_layout)

        model = QStandardItemModel(0, 8, project_frame)
        for column, (label, icon, icon_only) in enumerate(
            (
                (i18n.tr("Name"), None, False),
                (i18n.tr("Team"), None, False),
                (i18n.tr("Updated"), RELOAD_ICON, False),
                (i18n.tr("Created"), None, False),
                # Icons only, as on the cards: the table stays narrow
                (i18n.tr("Maps"), MAP_ICON, True),
                (i18n.tr("Vectors"), VECTOR_ICON, True),
                (i18n.tr("Rasters"), RASTER_ICON, True),
                (i18n.tr("Storage"), None, False),
            )
        ):
            header = QStandardItem("" if icon_only else label)
            header.setToolTip(label)
            if icon is not None:
                header.setIcon(icon)
            model.setHorizontalHeaderItem(column, header)
        proxy = _ProjectFilter(project_frame)
        proxy.setSourceModel(model)

        grid = _ProjectGrid()
        grid.setViewMode(QListView.ViewMode.IconMode)
        grid.setResizeMode(Q_LIST_VIEW_RESIZE_MODE.Adjust)
        grid.setMovement(QListView.Movement.Static)
        grid.setUniformItemSizes(True)
        grid.setMouseTracking(True)  # hover outline of the cards
        grid.setModel(proxy)

        table = QTreeView()
        table.setRootIsDecorated(False)
        table.setUniformRowHeights(True)
        table.setAlternatingRowColors(True)
        table.setIconSize(QSize(48, 27))
        table.setItemDelegateForColumn(_COL_TEAM, _SmallIconDelegate(table))
        table.setModel(proxy)
        table.setSortingEnabled(True)
        table.sortByColumn(_COL_UPDATED, Qt.SortOrder.DescendingOrder)
        header = table.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Stretch)
        # One selection for both views: switching keeps the chosen project
        table.setSelectionModel(grid.selectionModel())

        for view in (grid, table):
            view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            view.setContextMenuPolicy(QT_CUSTOM_CONTEXT_MENU)
            view.customContextMenuRequested.connect(
                lambda pos, v=view: self._show_context_menu(v, pos)
            )
            view.doubleClicked.connect(self._on_project_double_clicked)
        grid.selectionModel().selectionChanged.connect(self.on_project_selected)

        # Shown instead of the projects while loading, or when there are none
        message_page = QWidget()
        message_layout = QVBoxLayout(message_page)
        message_layout.addStretch()
        message_label = QLabel()
        message_label.setWordWrap(True)
        message_label.setAlignment(QT_ALIGN.AlignCenter)
        message_layout.addWidget(message_label)
        message_button_layout = QHBoxLayout()
        message_layout.addLayout(message_button_layout)
        message_layout.addStretch()

        stack = QStackedWidget()
        stack.addWidget(grid)
        stack.addWidget(table)
        stack.addWidget(message_page)
        frame_layout.addWidget(stack)

        project_frame.setLayout(frame_layout)

        table_view = settings_manager.get(PROJECT_VIEW_KEY) == "table"
        view_buttons.button(1 if table_view else 0).setChecked(True)
        view_buttons.idClicked.connect(self._on_view_changed)

        return {
            "project_frame": project_frame,
            "team_combo": team_combo,
            "search_input": search_input,
            "model": model,
            "proxy": proxy,
            "grid": grid,
            "table": table,
            "stack": stack,
            "view_buttons": view_buttons,
            "message_label": message_label,
            "message_button_layout": message_button_layout,
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
        """Show a message instead of the projects."""
        self._clear_list()
        section = self.project_section
        section["message_label"].setText(text)
        button_layout = section["message_button_layout"]
        while button_layout.count():
            old = button_layout.takeAt(0).widget()
            if old is not None:
                old.deleteLater()
        if button is not None:
            button_layout.addWidget(button, alignment=QT_ALIGN.AlignCenter)
        section["stack"].setCurrentIndex(2)

    def _show_projects(self) -> None:
        """Show the projects in the chosen view (0 grid, 1 table)."""
        section = self.project_section
        view_id = section["view_buttons"].checkedId()
        section["stack"].setCurrentIndex(view_id)
        current = section["grid"].selectionModel().currentIndex()
        if current.isValid():
            section["stack"].currentWidget().scrollTo(current)

    def _on_view_changed(self, view_id: int) -> None:
        settings_manager.store(PROJECT_VIEW_KEY, "table" if view_id else "grid")
        if self.project_section["model"].rowCount():
            self._show_projects()

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
        fallback_icon = QIcon(badge_pixmap("#9ca3af", ORGANIZATION_ICON, 32))
        for org in organizations:
            org_combo.addItem(fallback_icon, org.name, org)
            if org.iconImage:
                fetch_image(
                    api.user.resolve_avatar_url(org.iconImage),
                    org_combo,
                    lambda img, org_id=org.id: self._set_organization_icon(org_id, img),
                )
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

    def _set_organization_icon(self, org_id: str, img: QImage) -> None:
        # The combo may have been refilled meanwhile: find the org by id
        combo = self.account_org_panel["org_combo"]
        for i in range(combo.count()):
            org = combo.itemData(i)
            if org is not None and org.id == org_id:
                combo.setItemIcon(i, QIcon(_rounded(cover_image(img, 64, 64))))

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
            combo.addItem(_team_icon(team), team.name, team.id)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _clear_list(self) -> None:
        self.project_section["model"].setRowCount(0)
        self.on_project_selected()

    def _fill_projects(self, projects: List[ProjectInOrganization]) -> None:
        self._clear_list()
        if not projects:
            self._set_list_message(i18n.tr("No projects in this organization."))
            return
        model = self.project_section["model"]
        for project in projects:
            row = _project_row(project, self._placeholder_thumbnail)
            model.appendRow(row)
            if project.thumbnailImageUrl:
                cell = QPersistentModelIndex(row[_COL_NAME].index())
                fetch_image(
                    f"{project.thumbnailImageUrl}&w=320&h=180",
                    self,
                    lambda img, cell=cell: self._set_thumbnail(cell, img),
                )
        self.filter_projects()
        self._show_projects()
        self._select_project_by_id(self._wanted_project_id)

    def _set_thumbnail(self, cell: QPersistentModelIndex, img: QImage) -> None:
        if not cell.isValid():
            return  # the list was reloaded meanwhile
        model = self.project_section["model"]
        icon = QIcon(
            QPixmap.fromImage(
                cover_image(img, _THUMBNAIL_SIZE.width(), _THUMBNAIL_SIZE.height())
            )
        )
        model.setData(model.index(cell.row(), cell.column()), icon, _DECORATION_ROLE)

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

    @staticmethod
    def _project_at(index: QModelIndex) -> Optional[ProjectInOrganization]:
        if not index.isValid():
            return None
        return index.siblingAtColumn(_COL_NAME).data(QT_USER_ROLE)

    def on_project_selected(self, *_):
        selected = self.project_section["grid"].selectionModel().selectedIndexes()
        self.selected_project = self._project_at(selected[0]) if selected else None
        self.button_panel["ok_btn"].setEnabled(self.selected_project is not None)

    def _select_index(self, index: QModelIndex) -> None:
        flags = QItemSelectionModel.SelectionFlag
        self.project_section["grid"].selectionModel().setCurrentIndex(
            index, flags.ClearAndSelect | flags.Rows
        )

    def _on_project_double_clicked(self, index: QModelIndex) -> None:
        if self._project_at(index) is not None:
            self._select_index(index)
            self.accept()

    def _show_context_menu(self, view: QAbstractItemView, position) -> None:
        index = view.indexAt(position)
        project = self._project_at(index)
        if project is None:
            return
        self._select_index(index)
        menu = QMenu(self)
        open_web_action = menu.addAction(i18n.tr("Open in Web App"))
        open_web_action.triggered.connect(lambda: self.open_in_web(project))
        if project.teamId in self.admin_team_ids:
            edit_action = menu.addAction(i18n.tr("Edit Project"))
            edit_action.triggered.connect(lambda: self.edit_project(project))
            menu.addSeparator()
            delete_action = menu.addAction(i18n.tr("Delete Project"))
            delete_action.triggered.connect(lambda: self.delete_project(project))
        exec_menu(menu, view.viewport().mapToGlobal(position))

    def open_in_web(self, project: ProjectInOrganization) -> None:
        webbrowser.open(
            f"{api.client.server_url()}/organization/{self.current_org_id}"
            f"/team/{project.teamId}/project/{project.id}"
        )

    def filter_projects(self, *_):
        """Filter the projects by name and team"""
        proxy = self.project_section["proxy"]
        proxy.text = self.project_section["search_input"].text().lower()
        proxy.team_id = self.project_section["team_combo"].currentData()
        before = self.selected_project
        proxy.invalidateFilter()
        if before is not None and self.selected_project is not before:
            # Qt moves the selection to a neighbor when the selected project
            # is filtered out: do not pick a project the user did not choose
            self.project_section["grid"].selectionModel().clear()
        self.on_project_selected()

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
        proxy = self.project_section["proxy"]
        for row in range(proxy.rowCount()):
            index = proxy.index(row, _COL_NAME)
            project = index.data(QT_USER_ROLE)
            if project is not None and project.id == project_id:
                self._select_index(index)
                self.project_section["stack"].currentWidget().scrollTo(index)
                return

    # --- Project create / edit / delete ----------------------------------

    def _set_busy(self, busy: bool) -> None:
        self.button_panel["ok_btn"].setEnabled(
            not busy and self.selected_project is not None
        )
        self.button_panel["new_project_btn"].setEnabled(
            not busy and bool(self.admin_team_ids)
        )
        self.project_section["stack"].setEnabled(not busy)

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
                ].setMaximum(math.ceil(total))  # SU may be fractional; Qt wants int
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
