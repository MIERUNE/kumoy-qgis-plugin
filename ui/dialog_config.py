import json
import os
import webbrowser

from PyQt5.QtWidgets import (
    QDialog,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
)
from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt import uic

from ..qgishub.auth_manager import AuthManager
from ..qgishub.config import config
from ..qgishub.constants import LOG_CATEGORY
from ..settings_manager import SettingsManager


class DialogConfig(QDialog):
    def __init__(self):
        super().__init__()
        self.ui = uic.loadUi(
            os.path.join(os.path.dirname(__file__), "dialog_config.ui"), self
        )

        # Set type hints for UI
        self.buttonClose: QPushButton = self.ui.buttonClose
        self.buttonLogin: QPushButton = self.ui.buttonLogin
        self.buttonLogout: QPushButton = self.ui.buttonLogout
        self.labelSupabaseStatus: QLabel = self.ui.labelSupabaseStatus
        self.labelUserInfo: QLabel = self.ui.labelUserInfo
        self.mGroupBoxStratoServerConfig: QGroupBox = (
            self.ui.mGroupBoxStratoServerConfig
        )
        self.cognitoURL: QLineEdit = self.ui.cognitoURL
        self.cognitoClientID: QLineEdit = self.ui.cognitoClientID
        self.stratoURL: QLineEdit = self.ui.stratoURL

        self.buttonClose.clicked.connect(self.reject)

        # load saved server settings
        self.load_server_settings()

        # Set up Supabase login tab connections
        self.buttonLogin.clicked.connect(self.login)
        self.buttonLogout.clicked.connect(self.logout)

        # Initialize auth manager
        self.auth_manager = AuthManager(port=9248)

        self.update_login_status()

    def closeEvent(self, event):
        self.save_server_settings()
        super().closeEvent(event)

    def update_login_status(self):
        """Update the login status display based on stored tokens"""
        settings_manager = SettingsManager()
        id_token = settings_manager.get_setting("id_token")
        user_info_str = settings_manager.get_setting("user_info")

        if id_token:
            self.labelSupabaseStatus.setText("Logged in")
            self.labelSupabaseStatus.setStyleSheet("color: green; font-weight: bold;")
            self.buttonLogout.setEnabled(True)

            # Display user info if available
            if user_info_str:
                try:
                    user_info = json.loads(user_info_str)
                    email = user_info.get("email", "")
                    name = user_info.get("user_metadata", {}).get("full_name", "")

                    if name and email:
                        self.labelUserInfo.setText(f"Logged in as: {name}\n{email}")
                    elif email:
                        self.labelUserInfo.setText(f"Logged in as: {email}")
                except json.JSONDecodeError:
                    self.labelUserInfo.setText("")
        else:
            self.labelSupabaseStatus.setText("Not logged in")
            self.labelSupabaseStatus.setStyleSheet("")
            self.labelUserInfo.setText("")
            self.buttonLogout.setEnabled(False)

    def login(self):
        """Initiate the Google OAuth login flow via Supabase"""
        try:
            if not self.validate_custom_server_settings():
                return
            self.save_server_settings()

            # Start the authentication process
            success, result = self.auth_manager.authenticate()

            if not success:
                QMessageBox.warning(
                    self, "Login Error", f"Failed to start authentication: {result}"
                )
                return

            # Open the authorization URL in the default browser
            auth_url = result
            QgsMessageLog.logMessage(
                f"Opening browser to: {auth_url}", LOG_CATEGORY, Qgis.Info
            )
            webbrowser.open(auth_url)

            # Wait for the callback (this will block until authentication completes or times out)
            QgsMessageLog.logMessage(
                "Waiting for authentication to complete...", LOG_CATEGORY, Qgis.Info
            )
            success, error = self.auth_manager.wait_for_callback(timeout=300)

            if not success:
                QMessageBox.warning(
                    self, "Login Error", f"Authentication failed: {error}"
                )
                return

            # Authentication successful, get the tokens and user info
            id_token = self.auth_manager.get_id_token()
            refresh_token = self.auth_manager.get_refresh_token()
            user_info = self.auth_manager.get_user_info()

            # Store the tokens in settings
            settings_manager = SettingsManager()
            settings_manager.store_setting("id_token", id_token)
            settings_manager.store_setting("refresh_token", refresh_token)

            if user_info:
                settings_manager.store_setting("user_info", json.dumps(user_info))

            QgsMessageLog.logMessage(
                "Authentication successful!", LOG_CATEGORY, Qgis.Success
            )
            QMessageBox.information(
                self, "Login Success", "You have successfully logged in!"
            )

            # Update the UI
            self.update_login_status()

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error during login: {str(e)}", LOG_CATEGORY, Qgis.Critical
            )
            QMessageBox.critical(
                self, "Login Error", f"An error occurred during login: {str(e)}"
            )

    def logout(self):
        """Log out by clearing stored tokens"""
        try:
            settings_manager = SettingsManager()
            settings_manager.store_setting("id_token", "")
            settings_manager.store_setting("refresh_token", "")
            settings_manager.store_setting("user_info", "")

            QgsMessageLog.logMessage("Logged out successfully", LOG_CATEGORY, Qgis.Info)
            QMessageBox.information(
                self, "Logout", "You have been logged out successfully."
            )

            # Update the UI
            self.update_login_status()

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error during logout: {str(e)}", LOG_CATEGORY, Qgis.Critical
            )
            QMessageBox.critical(
                self, "Logout Error", f"An error occurred during logout: {str(e)}"
            )

    def save_server_settings(self):
        """サーバー設定を保存する"""
        settings_manager = SettingsManager()

        # カスタムサーバーの設定を保存
        use_custom_server = self.mGroupBoxStratoServerConfig.isChecked()
        custom_cognito_url = self.cognitoURL.text().strip()
        custom_cognito_client_id = self.cognitoClientID.text().strip()
        custom_server_url = self.stratoURL.text().strip()

        settings_manager.store_setting(
            "use_custom_server", "true" if use_custom_server else "false"
        )
        settings_manager.store_setting("custom_cognito_url", custom_cognito_url)
        settings_manager.store_setting(
            "custom_cognito_client_id", custom_cognito_client_id
        )
        settings_manager.store_setting("custom_server_url", custom_server_url)

        # 設定を保存した後、configを更新
        config.load_settings()

    def load_server_settings(self):
        """保存されたサーバー設定を読み込む"""
        settings_manager = SettingsManager()

        # 保存された設定を読み込む
        use_custom_server = settings_manager.get_setting("use_custom_server") == "true"
        custom_cognito_url = settings_manager.get_setting("custom_cognito_url") or ""
        custom_cognito_client_id = (
            settings_manager.get_setting("custom_cognito_client_id") or ""
        )
        custom_server_url = settings_manager.get_setting("custom_server_url") or ""

        # UIに設定を反映
        self.mGroupBoxStratoServerConfig.setChecked(use_custom_server)
        self.cognitoURL.setText(custom_cognito_url)
        self.cognitoClientID.setText(custom_cognito_client_id)
        self.stratoURL.setText(custom_server_url)

    def validate_custom_server_settings(self) -> bool:
        """カスタムサーバー設定のバリデーション"""
        if not self.mGroupBoxStratoServerConfig.isChecked():
            return True

        # 必要な設定項目をチェック
        missing_settings = []
        if not self.stratoURL.text().strip():
            missing_settings.append("Server URL")
        if not self.cognitoURL.text().strip():
            missing_settings.append("Cognito URL")
        if not self.cognitoClientID.text().strip():
            missing_settings.append("Cognito Client ID")

        # 未入力項目がある場合はメッセージボックスを表示
        if missing_settings:
            missing_text = ", ".join(missing_settings)
            QMessageBox.warning(
                self,
                "Custom Server Configuration Error",
                f"The following settings are missing:\n{missing_text}\n\nPlease configure them before logging in.",
            )
            return False

        return True
