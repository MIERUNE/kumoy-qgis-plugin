import json
import os
import webbrowser

from PyQt5.QtWidgets import QDialog, QMessageBox
from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt import uic

from ..qgishub.auth_manager import AuthManager
from ..qgishub.constants import LOG_CATEGORY
from ..settings_manager import SettingsManager


class DialogConfig(QDialog):
    def __init__(self):
        super().__init__()
        self.ui = uic.loadUi(
            os.path.join(os.path.dirname(__file__), "dialog_config.ui"), self
        )

        self.ui.buttonClose.clicked.connect(self.reject)

        # Set up Supabase login tab connections
        self.ui.buttonLogin.clicked.connect(self.login)
        self.ui.buttonLogout.clicked.connect(self.logout)

        # Initialize auth manager
        self.auth_manager = AuthManager(port=9248)

        self.update_login_status()

    def closeEvent(self, event):
        super().closeEvent(event)

    def update_login_status(self):
        """Update the login status display based on stored tokens"""
        settings_manager = SettingsManager()
        id_token = settings_manager.get_setting("id_token")
        user_info_str = settings_manager.get_setting("user_info")

        if id_token:
            self.ui.labelSupabaseStatus.setText("Logged in")
            self.ui.labelSupabaseStatus.setStyleSheet(
                "color: green; font-weight: bold;"
            )
            self.ui.buttonLogout.setEnabled(True)

            # Display user info if available
            if user_info_str:
                try:
                    user_info = json.loads(user_info_str)
                    email = user_info.get("email", "")
                    name = user_info.get("user_metadata", {}).get("full_name", "")

                    if name and email:
                        self.ui.labelUserInfo.setText(f"Logged in as: {name}\n{email}")
                    elif email:
                        self.ui.labelUserInfo.setText(f"Logged in as: {email}")
                except json.JSONDecodeError:
                    self.ui.labelUserInfo.setText("")
        else:
            self.ui.labelSupabaseStatus.setText("Not logged in")
            self.ui.labelSupabaseStatus.setStyleSheet("")
            self.ui.labelUserInfo.setText("")
            self.ui.buttonLogout.setEnabled(False)

    def login(self):
        """Initiate the Google OAuth login flow via Supabase"""
        try:
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
