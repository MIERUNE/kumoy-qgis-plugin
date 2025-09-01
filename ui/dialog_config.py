import json
import os
import webbrowser

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
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
)
from qgis.utils import iface

from ..settings_manager import get_settings, store_setting
from ..strato.auth_manager import AuthManager
from ..strato.constants import LOG_CATEGORY
from ..version import exec_dialog


class DialogConfig(QDialog):
    def __init__(self):
        super().__init__()
        self.setupUi()

        self.close_button.clicked.connect(self.reject)

        # load saved server settings
        self.load_server_settings()

        # Set up Supabase login tab connections
        self.login_button.clicked.connect(self.login)
        self.logout_button.clicked.connect(self.logout)

        # Initialize auth manager
        self.auth_manager = AuthManager(port=9248)

        self.update_login_status()

    def setupUi(self):
        # Set dialog properties
        self.setObjectName("Dialog")
        self.resize(400, 624)
        self.setMinimumSize(400, 0)
        self.setWindowTitle(self.tr("Authentication"))

        # Create main vertical layout
        verticalLayout = QVBoxLayout(self)

        # Top horizontal layout for icon
        horizontalLayout_3 = QHBoxLayout()

        # Icon label
        logo_icon_label = QLabel()
        logo_icon_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        logo_icon_label.setMinimumSize(150, 150)
        logo_icon_label.setMaximumSize(125, 125)
        icon_path = os.path.join(os.path.dirname(__file__), "../imgs/icon.svg")
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            logo_icon_label.setPixmap(pixmap)
        logo_icon_label.setScaledContents(True)
        logo_icon_label.setAlignment(Qt.AlignCenter)
        logo_icon_label.setWordWrap(False)
        horizontalLayout_3.addWidget(logo_icon_label)

        verticalLayout.addLayout(horizontalLayout_3)

        # Vertical spacer
        verticalSpacer = QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Fixed)
        verticalLayout.addItem(verticalSpacer)

        # Info label with HTML content
        version_and_credits_label = QLabel()
        version_and_credits_label.setText(
            '<html>\
                <head/>\
                <body>\
                    <div>\
                        STRATO<br />\
                        v0.0.0<br /><br />\
                        Powered by <a href="https://develop.d1hkxct7k1njv6.amplifyapp.com/"><span style=" text-decoration: underline; color:#0000ff;">MIERUNE Inc.</span></a>\
                    </div>\
                </body>\
            </html>'
        )
        version_and_credits_label.setScaledContents(False)
        version_and_credits_label.setAlignment(Qt.AlignCenter)
        version_and_credits_label.setOpenExternalLinks(True)
        verticalLayout.addWidget(version_and_credits_label)

        # Status label
        self.login_status_label = QLabel()
        self.login_status_label.setText("Not logged in")
        self.login_status_label.setAlignment(Qt.AlignCenter)
        verticalLayout.addWidget(self.login_status_label)

        # User info label
        self.user_info_label = QLabel()
        self.user_info_label.setText("")
        self.user_info_label.setAlignment(Qt.AlignCenter)
        self.user_info_label.setWordWrap(True)
        verticalLayout.addWidget(self.user_info_label)

        # Collapsible group box for server config
        self.custom_server_config_group = QgsCollapsibleGroupBox()
        self.custom_server_config_group.setEnabled(True)
        self.custom_server_config_group.setTitle("Custom Strato server config")
        self.custom_server_config_group.setCheckable(True)
        self.custom_server_config_group.setChecked(False)
        self.custom_server_config_group.setCollapsed(False)
        self.custom_server_config_group.setSaveCheckedState(False)

        # Grid layout for server config
        gridLayout = QGridLayout(self.custom_server_config_group)

        # Cognito URL row
        cognito_url_label = QLabel()
        cognito_url_label.setText("Cognito URL")
        gridLayout.addWidget(cognito_url_label, 1, 0)

        self.cognito_url_input = QLineEdit()
        self.cognito_url_input.setText("")
        gridLayout.addWidget(self.cognito_url_input, 1, 1)

        # Cognito Client ID row
        cognito_client_id_label = QLabel()
        cognito_client_id_label.setText("")
        gridLayout.addWidget(cognito_client_id_label, 2, 0)

        self.cognito_client_id_input = QLineEdit()
        self.cognito_client_id_input.setText("")
        gridLayout.addWidget(self.cognito_client_id_input, 2, 1)

        # Server URL row
        server_url_label = QLabel()
        server_url_label.setText("Server URL")
        gridLayout.addWidget(server_url_label, 3, 0)

        self.strato_server_url_input = QLineEdit()
        self.strato_server_url_input.setText("")
        gridLayout.addWidget(self.strato_server_url_input, 3, 1)

        verticalLayout.addWidget(self.custom_server_config_group)

        # Login/Logout buttons layout
        horizontalLayout_2 = QHBoxLayout()

        self.login_button = QPushButton()
        self.login_button.setText("Login")
        horizontalLayout_2.addWidget(self.login_button)

        self.logout_button = QPushButton()
        self.logout_button.setEnabled(False)
        self.logout_button.setText("Logout")
        horizontalLayout_2.addWidget(self.logout_button)

        verticalLayout.addLayout(horizontalLayout_2)

        # Close button layout
        horizontalLayout = QHBoxLayout()

        horizontalSpacer = QSpacerItem(
            40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum
        )
        horizontalLayout.addItem(horizontalSpacer)

        self.close_button = QPushButton()
        self.close_button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.close_button.setText("Close")
        horizontalLayout.addWidget(self.close_button)

        verticalLayout.addLayout(horizontalLayout)

    def tr(self, message):
        """Get the translation for a string using Qt translation API"""
        return QCoreApplication.translate("DialogConfig", message)

    def closeEvent(self, event):
        self.save_server_settings()
        super().closeEvent(event)

    def update_login_status(self):
        """Update the login status display based on stored tokens"""
        id_token = get_settings().id_token
        user_info_str = get_settings().user_info

        if id_token:
            self.login_status_label.setText(self.tr("Logged in"))
            self.login_status_label.setStyleSheet(
                "color: green; font-weight: bold; font-size: 24px;"
            )
            self.logout_button.setEnabled(True)

            # Display user info if available
            if user_info_str:
                try:
                    user_info = json.loads(user_info_str)
                    email = user_info.get("email", "")
                    name = user_info.get("user_metadata", {}).get("full_name", "")

                    if name and email:
                        self.user_info_label.setText(
                            self.tr("Logged in as: {}\n{}").format(name, email)
                        )
                    elif email:
                        self.user_info_label.setText(
                            self.tr("Logged in as: {}").format(email)
                        )
                except json.JSONDecodeError:
                    self.user_info_label.setText("")
        else:
            self.login_status_label.setText(self.tr("Not logged in"))
            self.login_status_label.setStyleSheet("")
            self.user_info_label.setText("")
            self.logout_button.setEnabled(False)

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
        user_info = self.auth_manager.get_user_info()

        # Store the tokens in settings
        store_setting("id_token", id_token)
        store_setting("refresh_token", refresh_token)

        if user_info:
            store_setting("user_info", json.dumps(user_info))

        QgsMessageLog.logMessage(
            "Authentication successful!", LOG_CATEGORY, Qgis.Success
        )
        QMessageBox.information(
            self, self.tr("Login Success"), self.tr("You have successfully logged in!")
        )

        # Update the UI
        self.update_login_status()

        # Show project selection dialog if project is not selected after successful login
        self.check_and_show_project_selection()

    def login(self):
        """Initiate the Google OAuth login flow via Supabase"""
        try:
            if not self.validate_custom_server_settings():
                return
            self.save_server_settings()

            # Update status to show login is in progress
            self.login_status_label.setText(self.tr("Logging in..."))
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

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error during login: {str(e)}", LOG_CATEGORY, Qgis.Critical
            )
            QMessageBox.critical(
                self,
                self.tr("Login Error"),
                self.tr("An error occurred during login: {}").format(str(e)),
            )
            # Reset status and re-enable login button on error
            self.update_login_status()
            self.login_button.setEnabled(True)

    def logout(self):
        """Log out by clearing stored tokens"""
        try:
            store_setting("id_token", "")
            store_setting("refresh_token", "")
            store_setting("user_info", "")
            store_setting("selected_project_id", "")

            QgsMessageLog.logMessage("Logged out successfully", LOG_CATEGORY, Qgis.Info)
            QMessageBox.information(
                self,
                self.tr("Logout"),
                self.tr("You have been logged out successfully."),
            )

            # Update the UI
            self.update_login_status()

            # Refresh browser panel to update the name
            iface.browserModel().reload()

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error during logout: {str(e)}", LOG_CATEGORY, Qgis.Critical
            )
            QMessageBox.critical(
                self,
                self.tr("Logout Error"),
                self.tr("An error occurred during logout: {}").format(str(e)),
            )

    def save_server_settings(self):
        """サーバー設定を保存する"""

        # カスタムサーバーの設定を保存
        use_custom_server = self.custom_server_config_group.isChecked()
        custom_cognito_url = self.cognito_url_input.text().strip()
        custom_cognito_client_id = self.cognito_client_id_input.text().strip()
        custom_server_url = self.strato_server_url_input.text().strip()

        store_setting("use_custom_server", "true" if use_custom_server else "false")
        store_setting("custom_cognito_url", custom_cognito_url)
        store_setting("custom_cognito_client_id", custom_cognito_client_id)
        store_setting("custom_server_url", custom_server_url)

    def load_server_settings(self):
        """保存されたサーバー設定を読み込む"""

        # 保存された設定を読み込む
        use_custom_server = get_settings().use_custom_server == "true"
        custom_cognito_url = get_settings().custom_cognito_url or ""
        custom_cognito_client_id = get_settings().custom_cognito_client_id or ""
        custom_server_url = get_settings().custom_server_url or ""

        # UIに設定を反映
        self.custom_server_config_group.setChecked(use_custom_server)
        self.cognito_url_input.setText(custom_cognito_url)
        self.cognito_client_id_input.setText(custom_cognito_client_id)
        self.strato_server_url_input.setText(custom_server_url)

    def validate_custom_server_settings(self) -> bool:
        """カスタムサーバー設定のバリデーション"""
        if not self.custom_server_config_group.isChecked():
            return True

        # 必要な設定項目をチェック
        missing_settings = []
        if not self.strato_server_url_input.text().strip():
            missing_settings.append(self.tr("Server URL"))
        if not self.cognito_url_input.text().strip():
            missing_settings.append(self.tr("Cognito URL"))
        if not self.cognito_client_id_input.text().strip():
            missing_settings.append(self.tr("Cognito Client ID"))

        # 未入力項目がある場合はメッセージボックスを表示
        if missing_settings:
            missing_text = ", ".join(missing_settings)
            QMessageBox.warning(
                self,
                self.tr("Custom Server Configuration Error"),
                self.tr(
                    "The following settings are missing:\n{}\n\nPlease configure them before logging in."
                ).format(missing_text),
            )
            return False

        return True

    def check_and_show_project_selection(self):
        """Check if project is selected and show project selection dialog if needed"""
        QgsMessageLog.logMessage(
            "Project not selected, showing project selection dialog",
            LOG_CATEGORY,
            Qgis.Info,
        )

        # Close the config dialog first
        self.accept()

        # Import only when needed to avoid circular imports
        from .dialog_project_select import ProjectSelectDialog

        # Show project selection dialog
        dialog = ProjectSelectDialog()
        result = exec_dialog(dialog)

        if not result:
            return

        selected_project = dialog.get_selected_project()
        if not selected_project:
            return

        QgsMessageLog.logMessage(
            f"Project selected: {selected_project.name}",
            LOG_CATEGORY,
            Qgis.Info,
        )
