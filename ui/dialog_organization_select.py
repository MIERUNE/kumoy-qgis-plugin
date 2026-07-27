"""組織選択ダイアログ。

ブラウザのルート（選択中Organizationを表す）の「Select Organization」から開く。
アカウント情報と所属Organizationの一覧を表示し、1つを選んで設定に保存する。
Project選択は別ダイアログ（ProjectSelectDialog）の責務で、ここでは扱わない。
"""

import webbrowser
from typing import Optional

from qgis.PyQt.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import i18n
from ..kumoy import api
from ..kumoy.settings_manager import get_settings, store_setting
from ..pyqt_version import (
    Q_LIST_VIEW_RESIZE_MODE,
    QT_ALIGN,
    QT_NO_ITEM_FLAGS,
    QT_USER_ROLE,
    exec_dialog,
)
from .error_handler import handle_api_error
from .icons import RELOAD_ICON
from .remote_image_label import RemoteImageLabel


class OrganizationSelectDialog(QDialog):
    """所属Organizationの一覧から1つを選ぶダイアログ"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(i18n.tr("Select Organization"))
        self.resize(480, 520)
        self.setMinimumWidth(420)
        self.selected_organization: Optional[api.organization.OrganizationWithRole] = (
            None
        )
        self.setup_ui()
        self.load_user_info()
        self.load_organizations()
        self.load_saved_selection()

    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Account header (avatar + user name) with a refresh button
        header_layout = QHBoxLayout()
        self.avatar_label = RemoteImageLabel(size=(32, 32))
        self.avatar_label.set_circular_mask()
        self.avatar_label.setAlignment(QT_ALIGN.AlignCenter)
        header_layout.addWidget(self.avatar_label)

        self.user_name_label = QLabel(i18n.tr("Loading..."))
        header_layout.addWidget(self.user_name_label)
        header_layout.addStretch()

        refresh_button = QPushButton(RELOAD_ICON, "")
        refresh_button.setToolTip(i18n.tr("Refresh"))
        refresh_button.setFixedSize(32, 32)
        refresh_button.clicked.connect(self.reload_dialog)
        header_layout.addWidget(refresh_button)
        layout.addLayout(header_layout)

        org_label = QLabel(i18n.tr("Organization"))
        layout.addWidget(org_label)

        # Organization list
        self.org_list = QListWidget()
        self.org_list.setResizeMode(Q_LIST_VIEW_RESIZE_MODE.Adjust)
        self.org_list.setSpacing(4)
        self.org_list.itemSelectionChanged.connect(self.on_selection_changed)
        self.org_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.org_list, 1)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)

        help_btn = QPushButton(i18n.tr("Help"))
        help_btn.setAutoDefault(False)
        help_btn.clicked.connect(
            lambda: webbrowser.open(api.config.get_api_config().SERVER_URL)
        )
        button_layout.addWidget(help_btn)
        button_layout.addStretch()

        cancel_btn = QPushButton(i18n.tr("Cancel"))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        self.ok_btn = QPushButton(i18n.tr("OK"))
        self.ok_btn.setEnabled(False)
        self.ok_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.ok_btn)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def load_user_info(self):
        user = api.user.get_me()
        self.user_name_label.setText(user.name)
        if user.avatarImage:
            avatar_url = api.config.get_api_config().SERVER_URL + user.avatarImage
            self.avatar_label.load(avatar_url)
        elif len(user.name) > 0:
            self.avatar_label.setText(user.name[0].upper())

    def load_organizations(self):
        self.org_list.clear()
        organizations = api.organization.get_organizations()

        if not organizations:
            self._handle_no_organization()
            return

        for org in organizations:
            item = QListWidgetItem(self.org_list)
            widget = _OrganizationItemWidget(org)
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
    """Organization一覧の1件（名前＋プラン/ロール）"""

    def __init__(self, org: api.organization.OrganizationWithRole):
        super().__init__()
        layout = QVBoxLayout()
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        name_label = QLabel(org.name)
        layout.addWidget(name_label)

        if org.scheduledDeletionAt:
            subtitle = i18n.tr("Scheduled for deletion")
        else:
            subtitle = i18n.tr("{plan} Plan / {role}").format(
                plan=org.subscriptionPlan.capitalize(),
                role=org.role.capitalize(),
            )
        subtitle_label = QLabel(subtitle)
        subtitle_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(subtitle_label)

        self.setLayout(layout)


def select_organization() -> bool:
    """Organization選択ダイアログを開く。選択が保存されたら True を返す。"""
    dialog = OrganizationSelectDialog()
    return exec_dialog(dialog) and dialog.selected_organization is not None
