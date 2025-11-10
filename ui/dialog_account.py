import os
import webbrowser

from qgis.core import Qgis, QgsMessageLog, QgsProject
from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtGui import QPixmap
from qgis.PyQt.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..settings_manager import store_setting
from ..strato import api
from ..strato.constants import LOG_CATEGORY
from .dialog_login import read_version
from .remote_image_label import RemoteImageLabel


class DialogAccount(QDialog):
    """Dialog that shows the current STRATO account information."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server_url = ""
        self.cognito_url = ""
        self.cognito_client_id = ""
        self.account_settings_url = ""
        self.user_info = {}

        self._init_ui()
        self._load_user_info()
        self._load_server_config()

    def tr(self, message: str) -> str:
        """Qt translation helper."""
        return QCoreApplication.translate("DialogAccount", message)

    def _init_ui(self) -> None:
        self.setWindowTitle(self.tr("Account"))
        self.setMinimumSize(480, 360)
        self.setSizeGripEnabled(False)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(32, 32, 32, 32)
        main_layout.setSpacing(24)
        self.setLayout(main_layout)

        # Header: logo + powered by + version
        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        # icon:label
        icon_logo_hlayout = QHBoxLayout()
        icon_logo_hlayout.setSpacing(4)
        # icon
        icon_label = QLabel()
        icon_label.setFixedSize(24, 24)
        icon_label.setScaledContents(True)
        icon_pixmap = QPixmap(
            os.path.join(os.path.dirname(__file__), "../imgs", "icon.svg")
        )
        icon_label.setPixmap(icon_pixmap)
        # label
        product_label = QLabel("Strato")
        product_label.setStyleSheet("font-size: 18px; font-weight: 600;")
        # layout
        icon_logo_hlayout.addWidget(icon_label)
        icon_logo_hlayout.addWidget(product_label)

        # powered by
        powered_label = QLabel(
            self.tr('Powered by <a href="https://www.mierune.co.jp/">MIERUNE Inc.</a>')
        )
        powered_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        powered_label.setOpenExternalLinks(True)

        brand_layout = QVBoxLayout()
        brand_layout.setSpacing(4)
        brand_layout.addLayout(icon_logo_hlayout)
        brand_layout.addWidget(powered_label)
        header_layout.addLayout(brand_layout)
        header_layout.addStretch()

        version_label = QLabel(read_version())
        version_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        version_label.setStyleSheet("color: #777777; font-size: 12px;")
        header_layout.addWidget(version_label)
        # icon/label <-> version
        # powered by

        main_layout.addLayout(header_layout)

        # User profile section
        profile_layout = QVBoxLayout()
        profile_layout.setSpacing(12)
        profile_layout.setContentsMargins(0, 0, 0, 0)
        profile_layout.setAlignment(Qt.AlignCenter)

        # Avatar with image or initial + name
        self.avatar_label = RemoteImageLabel(size=(64, 64))
        self.avatar_label.set_circular_mask()
        self.avatar_label.setAlignment(Qt.AlignCenter)

        # Name label
        self.name_label = QLabel(self.tr("Unknown user"))
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setStyleSheet("font-size: 18px; font-weight: 600;")

        self.email_label = QLabel("")
        self.email_label.setAlignment(Qt.AlignCenter)
        self.email_label.setStyleSheet("font-size: 13px;")

        self.account_settings_button = QPushButton(self.tr("Account settings"))
        self.account_settings_button.setCursor(Qt.PointingHandCursor)
        self.account_settings_button.clicked.connect(self._open_account_settings)
        self.account_settings_button.setStyleSheet(
            """
            QPushButton {
                padding: 4px 8px;
            }
        """
        )

        profile_layout.addWidget(self.avatar_label, 0, Qt.AlignHCenter)
        profile_layout.addWidget(self.name_label, 0, Qt.AlignHCenter)
        profile_layout.addWidget(self.email_label, 0, Qt.AlignHCenter)
        profile_layout.addWidget(self.account_settings_button, 0, Qt.AlignHCenter)

        main_layout.addLayout(profile_layout)

        # Server configuration block
        server_layout = QVBoxLayout()
        server_layout.setSpacing(6)
        server_layout.setContentsMargins(0, 0, 0, 0)

        server_label = QLabel(self.tr("Server configuration"))
        server_label.setStyleSheet("font-weight: 600;")
        server_layout.addWidget(server_label)

        self.server_url_label = QLabel()
        self.server_url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.server_url_label.setStyleSheet("font-size: 12px;")
        server_layout.addWidget(self.server_url_label)

        main_layout.addLayout(server_layout)

        main_layout.addStretch()

        # Logout button
        self.logout_button = QPushButton(self.tr("Logout"))
        self.logout_button.setMinimumHeight(28)
        self.logout_button.setCursor(Qt.PointingHandCursor)
        self.logout_button.clicked.connect(self._logout)
        main_layout.addWidget(self.logout_button)

    def _load_user_info(self) -> None:
        self.user_info = api.user.get_me()

        name = self.user_info.name or self.user_info.email or self.tr("Unknown user")
        email = self.user_info.email or ""

        self.name_label.setText(name)
        self.email_label.setText(email)

        if self.user_info.avatarImage:
            config = api.config.get_api_config()
            avatar_url = config.SERVER_URL + self.user_info.avatarImage
            self.avatar_label.load(avatar_url)
        else:
            initials = self._create_initials(name)
            self.avatar_label.setText(initials)

    def _load_server_config(self) -> None:
        config = api.config.get_api_config()
        self.server_url = config.SERVER_URL
        self.account_settings_url = self.server_url.rstrip("/") + "/organization"
        self.server_url_label.setText(self.tr("Server URL\n{}").format(self.server_url))

    def _create_initials(self, name: str) -> str:
        parts = [part.strip() for part in name.split() if part.strip()]
        if not parts:
            return "??"
        initials = "".join(part[0].upper() for part in parts[:2])
        return initials or "??"

    def _open_account_settings(self) -> None:
        if not self.account_settings_url:
            return
        try:
            webbrowser.open(self.account_settings_url)
        except Exception as exc:  # pylint: disable=broad-except
            QMessageBox.warning(
                self,
                self.tr("Error"),
                self.tr("Error opening web browser: {}").format(str(exc)),
            )

    def _logout(self) -> None:
        if QgsProject.instance().isDirty():
            confirmed = QMessageBox.question(
                self,
                self.tr("Logout"),
                self.tr(
                    "You have unsaved changes. "
                    "Logging out will clear your current project. Continue?"
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )

            if confirmed != QMessageBox.Yes:
                return

        QgsProject.instance().clear()

        store_setting("id_token", "")
        store_setting("refresh_token", "")
        store_setting("user_info", "")
        store_setting("selected_project_id", "")
        store_setting("selected_organization_id", "")

        QgsMessageLog.logMessage(
            "Logged out via account dialog", LOG_CATEGORY, Qgis.Info
        )
        QMessageBox.information(
            self,
            self.tr("Logout"),
            self.tr("You have been logged out from STRATO."),
        )
        self.accept()
