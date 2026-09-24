"""組織選択ダイアログ。

ブラウザのルート（選択中Organizationを表す）の「Select Organization」から開く。
アカウント情報と所属Organizationの一覧、選択中Organizationの使用量を表示し、
1つを選んで設定に保存する。
Project選択は別ダイアログ（ProjectSelectDialog）の責務で、ここでは扱わない。
"""

import math
import webbrowser
from typing import Dict, Optional

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import i18n
from ..kumoy import api
from ..kumoy.api.error import format_api_error
from ..kumoy.constants import LOG_CATEGORY
from ..kumoy.settings_manager import get_settings, store_setting
from ..pyqt_version import (
    Q_LIST_VIEW_RESIZE_MODE,
    QT_ALIGN,
    QT_NO_ITEM_FLAGS,
    QT_TEXT_FORMAT_PLAIN,
    QT_USER_ROLE,
    exec_dialog,
)
from .error_handler import handle_api_error
from .icons import BUILDING_ICON
from .icons.darkmode import is_in_darkmode
from .remote_image_label import RemoteImageLabel

# Design tokens (color/*, number/radius/*) from the Kumoy dashboard.
_ACCENT = "#007ae0"
_MUTED_TEXT = "#888888"
# card_stroke is a light-theme token; dark QGIS needs a dimmer line or the
# frame outshines the rows inside it.
_CARD_STROKE = "rgba(255, 255, 255, 0.16)" if is_in_darkmode() else "#e7e7e7"

# Tile colors cycle so an organization keeps the same color across sessions.
_LOGO_COLORS = ("#005773", "#693996", "#bd494a")

_USAGE_KEYS = (
    "projects",
    "maps",
    "vectors",
    "rasters",
    "catalogs",
    "members",
    "editors",
    "storage",
)


def _usage_labels() -> Dict[str, str]:
    """Row labels. Built on call so the strings stay extractable literals."""
    return {
        "projects": i18n.tr("Projects"),
        "maps": i18n.tr("Maps"),
        "vectors": i18n.tr("Vectors"),
        "rasters": i18n.tr("Rasters"),
        "catalogs": i18n.tr("Catalogs"),
        "members": i18n.tr("Members"),
        "editors": i18n.tr("Editors"),
        "storage": i18n.tr("Storage"),
    }


def _get_usage_color(percentage: float) -> str:
    """Get color based on usage percentage"""
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


def _usage_bar_style(fill: str) -> str:
    return f"""
        QProgressBar {{
            border: none;
            border-radius: 3px;
            background-color: #e0e0e0;
        }}
        QProgressBar::chunk {{
            background-color: {fill};
            border-radius: 3px;
        }}
    """


# subscriptionPlan is a system identifier that differs from the plan name
# shown to users, so it must never be displayed as-is. Names are brand-fixed
# and stay untranslated.
_PLAN_DISPLAY_NAMES = {
    "FREE": "Community",
    "PRO": "Pro",
    "BUSINESS": "Business",
    "TEAM": "Corporate",
    "CUSTOM": "Enterprise",
}


def _plan_label(subscription_plan: str) -> str:
    """Plan display name. Unknown codes fall back to the raw API value."""
    return _PLAN_DISPLAY_NAMES.get(subscription_plan.upper(), subscription_plan)


class OrganizationSelectDialog(QDialog):
    """所属Organizationの一覧から1つを選ぶダイアログ"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(i18n.tr("Select Organization"))
        self.resize(550, 600)
        self.setMinimumWidth(500)
        self.selected_organization: Optional[api.organization.OrganizationWithRole] = (
            None
        )
        self.details_visible = False
        # Usage needs a detail request per organization, so keep what we fetched:
        # clicking back and forth in the list must not re-hit the API.
        self._detail_cache: Dict[str, api.organization.OrganizationDetail] = {}
        self.setup_ui()
        self.load_user_info()
        self.load_organizations()
        self.load_saved_selection()

    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        layout.addLayout(self._create_account_panel())

        # Organization list
        self.org_list = QListWidget()
        self.org_list.setResizeMode(Q_LIST_VIEW_RESIZE_MODE.Adjust)
        self.org_list.setSpacing(0)
        self.org_list.setStyleSheet(
            f"""
            QListWidget {{
                border: 1px solid {_CARD_STROKE};
                border-radius: 4px;
                padding: 12px;
            }}
            QListWidget::item {{
                border: 1px solid transparent;
                border-radius: 8px;
            }}
            QListWidget::item:selected {{
                border: 1px solid {_ACCENT};
                background-color: rgba(0, 122, 224, 0.08);
            }}
            QListWidget::item:hover {{
                background-color: rgba(0, 122, 224, 0.05);
            }}
        """
        )
        self.org_list.itemSelectionChanged.connect(self.on_selection_changed)
        self.org_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.org_list, 1)

        # "show details" link
        self.details_toggle = QLabel()
        self.details_toggle.linkActivated.connect(self.toggle_details)
        self._update_details_toggle_text()
        layout.addWidget(self.details_toggle)

        self.usage_panel = self._create_usage_panel()
        layout.addWidget(self.usage_panel["usage_frame"])
        self.usage_panel["usage_frame"].setVisible(self.details_visible)

        layout.addLayout(self._create_button_panel())
        self.setLayout(layout)

    def _create_account_panel(self) -> QVBoxLayout:
        """Account label with the signed-in user's avatar, name and email."""
        panel = QVBoxLayout()
        panel.setSpacing(8)

        panel.addWidget(QLabel(i18n.tr("Account")))

        user_layout = QHBoxLayout()
        user_layout.setSpacing(8)

        self.avatar_label = RemoteImageLabel(size=(32, 32))
        self.avatar_label.set_circular_mask()
        self.avatar_label.setAlignment(QT_ALIGN.AlignCenter)
        user_layout.addWidget(self.avatar_label)

        name_email_layout = QVBoxLayout()
        name_email_layout.setSpacing(2)
        self.user_name_label = QLabel(i18n.tr("Loading..."))
        self.user_name_label.setTextFormat(QT_TEXT_FORMAT_PLAIN)
        self.user_name_label.setStyleSheet("font-weight: 600;")
        name_email_layout.addWidget(self.user_name_label)
        self.user_email_label = QLabel()
        self.user_email_label.setTextFormat(QT_TEXT_FORMAT_PLAIN)
        self.user_email_label.setStyleSheet(f"color: {_MUTED_TEXT}; font-size: 12px;")
        name_email_layout.addWidget(self.user_email_label)
        user_layout.addLayout(name_email_layout)

        user_layout.addStretch()
        panel.addLayout(user_layout)
        return panel

    def _create_usage_panel(self) -> dict:
        """Create organization usage panel with progress bars.

        A grid keeps the three columns aligned while letting the name and value
        columns size to their content: fixed widths clip the widest value
        ("11.65SU / 10000SU") and longer translations of the row names.
        """
        usage_frame = QFrame()
        usage_layout = QGridLayout()
        usage_layout.setContentsMargins(0, 0, 0, 0)
        usage_layout.setHorizontalSpacing(10)
        usage_layout.setVerticalSpacing(6)
        usage_layout.setColumnStretch(2, 1)

        usage_widgets = {}
        labels = _usage_labels()
        for row, key in enumerate(_USAGE_KEYS):
            usage_layout.addWidget(QLabel(labels[key]), row, 0)

            usage_text = QLabel()
            usage_text.setAlignment(QT_ALIGN.AlignRight | QT_ALIGN.AlignVCenter)
            usage_layout.addWidget(usage_text, row, 1)

            progress_bar = QProgressBar()
            progress_bar.setTextVisible(False)
            progress_bar.setFixedHeight(6)
            progress_bar.setStyleSheet(_usage_bar_style(_get_usage_color(0)))
            usage_layout.addWidget(progress_bar, row, 2)

            usage_widgets[key] = {"label": usage_text, "progress": progress_bar}

        usage_frame.setLayout(usage_layout)
        return {"usage_frame": usage_frame, "usage_widgets": usage_widgets}

    def _create_button_panel(self) -> QHBoxLayout:
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)

        help_btn = QPushButton(i18n.tr("Help"))
        help_btn.setAutoDefault(False)
        help_btn.clicked.connect(
            lambda: webbrowser.open(api.config.get_api_config().SERVER_URL)
        )
        button_layout.addWidget(help_btn)

        self.org_settings_btn = QPushButton(i18n.tr("Organization Settings"))
        self.org_settings_btn.setAutoDefault(False)
        self.org_settings_btn.setEnabled(False)
        self.org_settings_btn.clicked.connect(self.open_organization_settings)
        button_layout.addWidget(self.org_settings_btn)

        button_layout.addStretch()

        cancel_btn = QPushButton(i18n.tr("Cancel"))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        self.ok_btn = QPushButton(i18n.tr("OK"))
        self.ok_btn.setEnabled(False)
        self.ok_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.ok_btn)

        return button_layout

    def load_user_info(self):
        user = api.user.get_me()
        self.user_name_label.setText(user.name)
        self.user_email_label.setText(user.email)
        if user.avatarImage:
            self.avatar_label.load(api.user.resolve_avatar_url(user.avatarImage))
        elif len(user.name) > 0:
            self.avatar_label.setText(user.name[0].upper())

    def load_organizations(self):
        self.org_list.clear()
        self._detail_cache.clear()
        organizations = api.organization.get_organizations()

        if not organizations:
            self._handle_no_organization()
            return

        for index, org in enumerate(organizations):
            item = QListWidgetItem(self.org_list)
            widget = _OrganizationItemWidget(
                org, _LOGO_COLORS[index % len(_LOGO_COLORS)]
            )
            item.setData(QT_USER_ROLE, org)
            item.setSizeHint(widget.sizeHint())
            self.org_list.addItem(item)
            self.org_list.setItemWidget(item, widget)

    def _handle_no_organization(self):
        """所属Organizationが無いとき、作成導線を出す"""
        msg_widget = QWidget()
        msg_layout = QVBoxLayout(msg_widget)
        msg_layout.setContentsMargins(12, 12, 12, 12)
        msg_layout.setSpacing(8)

        msg_label = QLabel(
            i18n.tr("No organization available. Please create one to get started.")
        )
        msg_label.setWordWrap(True)
        msg_label.setAlignment(QT_ALIGN.AlignCenter)
        msg_layout.addWidget(msg_label)

        create_org_btn = QPushButton(i18n.tr("Create Organization"))
        create_org_url = f"{api.config.get_api_config().SERVER_URL}/organization"
        create_org_btn.clicked.connect(lambda: webbrowser.open(create_org_url))
        msg_layout.addWidget(create_org_btn, alignment=QT_ALIGN.AlignCenter)

        item = QListWidgetItem(self.org_list)
        item.setFlags(QT_NO_ITEM_FLAGS)  # Make it non-selectable
        item.setSizeHint(msg_widget.sizeHint())
        self.org_list.addItem(item)
        self.org_list.setItemWidget(item, msg_widget)

    def on_selection_changed(self):
        current = self.org_list.currentItem()
        self.selected_organization = current.data(QT_USER_ROLE) if current else None
        self.ok_btn.setEnabled(bool(self.selected_organization))
        self.org_settings_btn.setEnabled(bool(self.selected_organization))
        self._refresh_usage_display()

    def _on_item_double_clicked(self, item: QListWidgetItem):
        if item.data(QT_USER_ROLE):
            self.accept()

    def load_saved_selection(self):
        org_id = get_settings().selected_organization_id
        if org_id:
            self._select_organization_by_id(org_id)

    def _select_organization_by_id(self, org_id: str):
        for i in range(self.org_list.count()):
            item = self.org_list.item(i)
            if item and (org := item.data(QT_USER_ROLE)) and org.id == org_id:
                self.org_list.setCurrentItem(item)
                break

    def toggle_details(self):
        """Toggle visibility of usage details panel"""
        self.details_visible = not self.details_visible
        self.usage_panel["usage_frame"].setVisible(self.details_visible)
        self._update_details_toggle_text()
        self._refresh_usage_display()

    def _update_details_toggle_text(self):
        label = (
            i18n.tr("Hide details") if self.details_visible else i18n.tr("Show details")
        )
        arrow = "&#9650;" if self.details_visible else "&#9660;"
        self.details_toggle.setText(f"<a href='#'>{label} {arrow}</a>")

    def open_organization_settings(self):
        """Open organization settings in web browser"""
        if not self.selected_organization:
            return

        base_url = api.config.get_api_config().SERVER_URL
        settings_url = (
            f"{base_url}/organization/{self.selected_organization.id}/setting"
        )
        try:
            webbrowser.open(settings_url)
        except Exception as e:
            msg = i18n.tr("Error opening web browser: {}").format(format_api_error(e))
            QgsMessageLog.logMessage(msg, LOG_CATEGORY, Qgis.Critical)
            QMessageBox.critical(self, i18n.tr("Error"), msg)

    def _refresh_usage_display(self):
        """Show usage for the highlighted organization, fetching it on demand.

        Only fetches while the panel is open: the detail request is per
        organization, so an unopened panel would spend one request per click.
        """
        if not self.details_visible:
            return

        org = self.selected_organization
        # Organizations pending deletion are unusable: their detail API returns
        # not found, so there is nothing to show
        if org is None or org.scheduledDeletionAt:
            self._clear_usage_display()
            return

        detail = self._detail_cache.get(org.id)
        if detail is None:
            try:
                detail = api.organization.get_organization(org.id)
            except Exception as e:
                handle_api_error(
                    e,
                    parent=self,
                    log_prefix=i18n.tr("Failed to load organization details"),
                )
                self._clear_usage_display()
                return
            self._detail_cache[org.id] = detail

        self._update_usage_display(detail)

    def _clear_usage_display(self):
        for key in _USAGE_KEYS:
            widgets = self.usage_panel["usage_widgets"][key]
            widgets["label"].setText("")
            widgets["progress"].setMaximum(1)
            widgets["progress"].setValue(0)
            widgets["progress"].setStyleSheet(_usage_bar_style(_get_usage_color(0)))

    def _update_usage_display(self, org_detail: api.organization.OrganizationDetail):
        """Update the usage display with organization details"""
        plan = org_detail.planSettings
        # (key, used, limit, pending)
        counted = [
            ("projects", org_detail.usage.projects, plan.maxProjects, 0),
            ("maps", org_detail.usage.styledMaps, plan.maxStyledMaps, 0),
            ("vectors", org_detail.usage.vectors, plan.maxVectors, 0),
            ("rasters", org_detail.usage.rasters, plan.maxRasters, 0),
            ("catalogs", org_detail.usage.catalogs, plan.maxCatalogs, 0),
            # Pending invites already occupy a seat: editor counts include them,
            # member counts do not.
            (
                "members",
                org_detail.usage.organizationMembers
                + org_detail.usage.organizationInvites,
                plan.maxOrganizationMembers,
                org_detail.usage.organizationInvites,
            ),
            # Purchased seats can exceed the plan quota, so the editor limit is
            # availableEditors rather than planSettings.maxEditors.
            (
                "editors",
                org_detail.usage.organizationEditors,
                org_detail.availableEditors,
                org_detail.usage.organizationEditorInvites,
            ),
        ]
        for key, used, limit, pending in counted:
            widgets = self.usage_panel["usage_widgets"][key]
            widgets["label"].setText(f"{used} / {limit}")
            widgets["progress"].setMaximum(max(limit, 1))
            widgets["progress"].setValue(min(limit, used))
            self._set_progress_color(widgets["progress"], used, limit, pending)

        storage = self.usage_panel["usage_widgets"]["storage"]
        used_units = org_detail.usage.usedStorageUnits
        total_units = org_detail.availableStorageUnits
        storage["label"].setText(f"{used_units:.2f}SU / {total_units:.0f}SU")
        storage["progress"].setMaximum(max(total_units, 1))
        storage["progress"].setValue(math.ceil(used_units))
        self._set_progress_color(storage["progress"], used_units, total_units)

    def _set_progress_color(
        self, progress_bar: QProgressBar, used: float, limit: int, pending: int = 0
    ):
        """Set progress bar color based on usage percentage"""
        percentage = (used / limit * 100) if limit > 0 else 0
        color = _get_usage_color(percentage)
        progress_bar.setStyleSheet(
            _usage_bar_style(_chunk_fill(color, used, limit, pending))
        )

    def reload_dialog(self):
        prev_id = self.selected_organization.id if self.selected_organization else None
        try:
            self.load_user_info()
            self.load_organizations()
        except Exception as e:
            handle_api_error(
                e, parent=self, log_prefix=i18n.tr("Failed to reload dialog")
            )
            return
        if prev_id:
            self._select_organization_by_id(prev_id)

    def accept(self):
        if self.selected_organization:
            store_setting("selected_organization_id", self.selected_organization.id)
        super().accept()


class _OrganizationItemWidget(QWidget):
    """Organization一覧の1件（ロゴタイル＋名前＋プラン/ロール）"""

    def __init__(self, org: api.organization.OrganizationWithRole, logo_color: str):
        super().__init__()
        layout = QHBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        logo_label = QLabel()
        logo_label.setFixedSize(32, 32)
        logo_label.setAlignment(QT_ALIGN.AlignCenter)
        logo_label.setPixmap(BUILDING_ICON.pixmap(14, 14))
        logo_label.setStyleSheet(f"background-color: {logo_color}; border-radius: 8px;")
        layout.addWidget(logo_label)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)

        name_label = QLabel(org.name)
        name_label.setTextFormat(QT_TEXT_FORMAT_PLAIN)
        name_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        text_layout.addWidget(name_label)

        if org.scheduledDeletionAt:
            subtitle = i18n.tr("Scheduled for deletion")
        else:
            # Role rides along on the plan line: it decides what the user may do
            # in the organization, and the design has no other slot for it.
            subtitle = i18n.tr("{plan} · {role}").format(
                plan=_plan_label(org.subscriptionPlan),
                role=org.role.capitalize(),
            )
        subtitle_label = QLabel(subtitle)
        subtitle_label.setStyleSheet(f"color: {_MUTED_TEXT}; font-size: 12px;")
        text_layout.addWidget(subtitle_label)

        layout.addLayout(text_layout)
        layout.addStretch()
        self.setLayout(layout)


def select_organization() -> bool:
    """Organization選択ダイアログを開く。選択が保存されたら True を返す。"""
    dialog = OrganizationSelectDialog()
    return exec_dialog(dialog) and dialog.selected_organization is not None
