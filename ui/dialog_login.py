import json
import os
import urllib.request
import webbrowser
from urllib.error import HTTPError

from qgis.core import Qgis, QgsMessageLog
from qgis.gui import QgsCollapsibleGroupBox
from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtGui import QPixmap
from qgis.PyQt.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpacerItem,
    QVBoxLayout,
)

from ..read_version import read_version
from ..sentry import init_sentry
from ..settings_manager import get_settings, store_setting
from ..kumoy import api
from ..kumoy.api.error import format_api_error
from ..kumoy.auth_manager import AuthManager
from ..kumoy.constants import LOG_CATEGORY
from ..pyqt_version import QT_ALIGN, Q_SIZE_POLICY
from .dialog_login_success import LoginSuccess


class DialogLogin(QDialog):
    def __init__(self):
        super().__init__()
        self.setupUi()

        # load saved server settings
        self.load_server_settings()
        self.update_login_status()

    def setupUi(self):
        # Set dialog properties
        self.setObjectName("Dialog")
        self.resize(400, 400)
        self.setMinimumSize(400, 0)
        self.setWindowTitle(self.tr("Authentication"))
        # set padding
        self.setContentsMargins(10, 10, 10, 10)

        # Create main vertical layout
        verticalLayout = QVBoxLayout(self)

        version_label = QLabel()
        version_label.setText(f"{read_version()}")
        version_label.setScaledContents(False)
        version_label.setAlignment(QT_ALIGN.AlignRight)
        version_label.setOpenExternalLinks(True)
        verticalLayout.addWidget(version_label)

        # Top horizontal layout for icon
        horizontalLayout_3 = QHBoxLayout()

        # Icon label
        logo_icon_label = QLabel()
        logo_icon_label.setSizePolicy(Q_SIZE_POLICY.Fixed, Q_SIZE_POLICY.Fixed)
        icon_path = os.path.join(os.path.dirname(__file__), "../imgs/icon.svg")
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            logo_icon_label.setPixmap(pixmap)
        logo_icon_label.setScaledContents(True)
        logo_icon_label.setAlignment(QT_ALIGN.AlignCenter)
        logo_icon_label.setWordWrap(False)
        horizontalLayout_3.addWidget(logo_icon_label)

        verticalLayout.addLayout(horizontalLayout_3)

        # Vertical spacer
        verticalSpacer = QSpacerItem(20, 20, Q_SIZE_POLICY.Minimum, Q_SIZE_POLICY.Fixed)
        verticalLayout.addItem(verticalSpacer)

        # Info label with HTML content
        version_and_credits_label = QLabel()
        version_and_credits_label.setText(
            self.tr(
                '<html>\
                <head/>\
                <body>\
                    <div>\
                        <h2>Welcome to Kumoy.</h2>\
                        <p>Powered by <a href="https://www.mierune.co.jp/"><span style=" text-decoration: underline; color:#0000ff;">MIERUNE Inc.</span></a></p>\
                    </div>\
                </body>\
            </html>'
            )
        )
        # padding
        version_and_credits_label.setContentsMargins(0, 20, 0, 40)
        version_and_credits_label.setScaledContents(False)
        version_and_credits_label.setAlignment(QT_ALIGN.AlignCenter)
        version_and_credits_label.setOpenExternalLinks(True)
        verticalLayout.addWidget(version_and_credits_label)

        # Collapsible group box for server config
        self.custom_server_config_group = QgsCollapsibleGroupBox()
        self.custom_server_config_group.setEnabled(True)
        self.custom_server_config_group.setTitle(self.tr("Custom server configuration"))
        self.custom_server_config_group.setCheckable(True)
        self.custom_server_config_group.setChecked(False)
        self.custom_server_config_group.setCollapsed(False)
        self.custom_server_config_group.setSaveCheckedState(False)

        # Grid layout for server config
        gridLayout = QGridLayout(self.custom_server_config_group)

        # Server URL row
        server_url_label = QLabel()
        server_url_label.setText(self.tr("Server URL"))
        gridLayout.addWidget(server_url_label, 1, 0)

        self.kumoy_server_url_input = QLineEdit()
        self.kumoy_server_url_input.setText("")
        gridLayout.addWidget(self.kumoy_server_url_input, 1, 1)

        verticalLayout.addWidget(self.custom_server_config_group)

        # Status label
        self.login_status_label = QLabel()
        self.login_status_label.setText("")
        self.login_status_label.setAlignment(QT_ALIGN.AlignCenter)
        verticalLayout.addWidget(self.login_status_label)

        # Login buttons layout
        self.login_button = QPushButton()
        self.login_button.setText(self.tr("Login"))
        self.login_button.clicked.connect(self.login)
        verticalLayout.addWidget(self.login_button)

    def tr(self, message):
        """Get the translation for a string using Qt translation API"""
        return QCoreApplication.translate("DialogLogin", message)

    def closeEvent(self, event):
        self.save_server_settings()
        super().closeEvent(event)

    def update_login_status(self):
        """Update the login status display based on stored tokens"""
        id_token = get_settings().id_token

        if id_token:
            self.login_status_label.setText(self.tr("Logged in"))
            self.login_status_label.setStyleSheet(
                "color: green; font-weight: bold; font-size: 24px;"
            )

        else:
            self.login_status_label.setText(self.tr(""))
            self.login_status_label.setStyleSheet("")

    def on_auth_completed(self, success: bool, error: str):
        """Handle authentication completion."""
        # Disconnect the signal to avoid multiple connections
        try:
            self.auth_manager.auth_completed.disconnect(self.on_auth_completed)
        except TypeError:
            pass  # Already disconnected

        self.login_button.setEnabled(True)

        if not success:
            QMessageBox.warning(
                self,
                self.tr("Login Error"),
                self.tr("Authentication failed: {}").format(error),
            )
            self.update_login_status()
            return

        # Authentication successful, get the tokens and user info
        id_token = self.auth_manager.get_id_token()
        refresh_token = self.auth_manager.get_refresh_token()

        # Store the tokens in settings
        store_setting("id_token", id_token)
        store_setting("refresh_token", refresh_token)

        QgsMessageLog.logMessage(
            "Authentication successful!", LOG_CATEGORY, Qgis.Success
        )

        # Show the custom login success dialog
        success_dialog = LoginSuccess(self)
        success_dialog.exec_()
        # Update the UI
        self.update_login_status()
        self.accept()
        init_sentry()  # 利用規約・プライバシポリシーを確認したログイン後にSentryを有効化

    def login(self):
        """Initiate the Google OAuth login flow via Supabase"""
        if not self.validate_custom_server_settings():
            return
        self.save_server_settings()

        try:
            # /api/_public/params エンドポイントからCognito設定を取得
            api_config = api.config.get_api_config()
            params_response = urllib.request.urlopen(
                f"{api_config.SERVER_URL}/api/_public/params"
            )
            params_data = json.loads(params_response.read().decode("utf-8"))
            cognito_url = f"https://{params_data['cognitoDomain']}"
            cognito_client_id = params_data["cognitoClientId"]

            self.auth_manager = AuthManager(
                cognito_url,
                cognito_client_id,
                port=9248,
            )
        except HTTPError as e:
            error_body = e.read().decode("utf-8")
            try:
                error_data = json.loads(error_body)
                error_message = error_data.get("error", format_api_error(e))
            except Exception:
                error_message = format_api_error(e)
            QgsMessageLog.logMessage(
                f"Error during login: {str(error_message)}", LOG_CATEGORY, Qgis.Critical
            )
            # Explicit network error
            QMessageBox.critical(
                self,
                self.tr("Login Error"),
                self.tr("An error occurred while logging in: {}").format(
                    str(error_message)
                ),
            )
            return
        except Exception as e:
            error_text = format_api_error(e)
            QgsMessageLog.logMessage(
                f"Error during login: {error_text}", LOG_CATEGORY, Qgis.Critical
            )
            # Explicit network error
            QMessageBox.critical(
                self,
                self.tr("Login Error"),
                self.tr("An error occurred while logging in: {}").format(error_text),
            )

            # Reset status and re-enable login button on error
            self.update_login_status()
            self.login_button.setEnabled(True)
            return

        # Update status to show login is in progress
        self.login_status_label.setText(self.tr("Signing you in..."))
        self.login_status_label.setStyleSheet("color: orange; font-weight: bold;")
        self.login_button.setEnabled(False)

        # Start the authentication process
        success, result = self.auth_manager.authenticate()

        if not success:
            QMessageBox.warning(
                self,
                self.tr("Login Error"),
                self.tr("Failed to start authentication: {}").format(result),
            )
            # Reset status on failure
            self.update_login_status()
            self.login_button.setEnabled(True)
            return

        # Connect to auth_completed signal
        self.auth_manager.auth_completed.connect(self.on_auth_completed)

        # Open the authorization URL in the default browser
        auth_url = result
        QgsMessageLog.logMessage(
            f"Opening browser to: {auth_url}", LOG_CATEGORY, Qgis.Info
        )
        webbrowser.open(auth_url)

        # Update status to indicate waiting for browser authentication
        self.login_status_label.setText(
            self.tr("Waiting for browser authentication...")
        )
        self.login_status_label.setStyleSheet("color: orange; font-weight: bold;")

        # Start async authentication
        QgsMessageLog.logMessage(
            "Waiting for authentication to complete...", LOG_CATEGORY, Qgis.Info
        )
        self.auth_manager.start_async_auth()

    def save_server_settings(self):
        """サーバー設定を保存する"""

        # カスタムサーバーの設定を保存
        use_custom_server = self.custom_server_config_group.isChecked()
        custom_server_url = self.kumoy_server_url_input.text().strip()

        store_setting("use_custom_server", "true" if use_custom_server else "false")
        store_setting("custom_server_url", custom_server_url)

    def load_server_settings(self):
        """保存されたサーバー設定を読み込む"""

        # 保存された設定を読み込む
        use_custom_server = get_settings().use_custom_server == "true"
        custom_server_url = get_settings().custom_server_url or ""

        # UIに設定を反映
        self.custom_server_config_group.setChecked(use_custom_server)
        self.kumoy_server_url_input.setText(custom_server_url)

    def validate_custom_server_settings(self) -> bool:
        """カスタムサーバー設定のバリデーション"""
        if not self.custom_server_config_group.isChecked():
            return True

        # 未入力項目がある場合はメッセージボックスを表示
        if self.kumoy_server_url_input.text().strip() == "":
            QMessageBox.warning(
                self,
                self.tr("Custom Server Configuration Error"),
                self.tr(
                    "Some required settings are missing:\n{}\n\nPlease update your configuration before logging in."
                ).format(self.tr("Server URL")),
            )
            return False

        if not self.kumoy_server_url_input.text().startswith("http"):
            QMessageBox.warning(
                self,
                self.tr("Custom Server Configuration Error"),
                self.tr("The Server URL must start with http or https."),
            )
            return False

        return True
