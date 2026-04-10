import json
import urllib.request
import webbrowser
from urllib.error import HTTPError, URLError

from qgis.core import Qgis, QgsMessageLog
from qgis.gui import QgsCollapsibleGroupBox
from qgis.PyQt.QtCore import QCoreApplication, QEvent
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

from ..kumoy import api
from ..kumoy.api.error import format_api_error
from ..kumoy.auth_manager import AuthManager
from ..kumoy.constants import LOG_CATEGORY
from ..plugin_version import is_plugin_version_compatible, read_plugin_version
from ..pyqt_version import (
    Q_SIZE_POLICY,
    QT_ALIGN,
    QT_TEXT_FORMAT_RICH,
    QT_TEXT_INTERACTION,
    exec_dialog,
)
from ..settings_manager import get_settings, store_setting
from .dialog_login_success import LoginSuccess
from .icons import MAIN_ICON


class DialogLogin(QDialog):
    def __init__(self):
        super().__init__()
        self.auth_manager = None
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
        version_label.setText(f"{read_plugin_version()}")
        version_label.setScaledContents(False)
        version_label.setAlignment(QT_ALIGN.AlignRight)
        version_label.setOpenExternalLinks(True)
        verticalLayout.addWidget(version_label)

        # Top horizontal layout for icon
        horizontalLayout_3 = QHBoxLayout()

        # Icon label
        logo_icon_label = QLabel()
        logo_icon_label.setSizePolicy(Q_SIZE_POLICY.Fixed, Q_SIZE_POLICY.Fixed)
        logo_icon_label.setPixmap(MAIN_ICON.pixmap(128, 128))
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

        # Login buttons layout
        self.login_button = QPushButton()
        self.login_button.setText(self.tr("Login"))
        self.login_button.clicked.connect(self.login)
        verticalLayout.addWidget(self.login_button)

        self.user_code_label = QLabel()
        self.user_code_label.setAlignment(QT_ALIGN.AlignCenter)
        self.user_code_label.setStyleSheet(
            "font-size: 28px; font-weight: bold; letter-spacing: 4px; padding: 8px; "
        )
        self.user_code_label.setTextInteractionFlags(
            QT_TEXT_INTERACTION.TextSelectableByMouse
        )
        self.user_code_label.hide()
        verticalLayout.addWidget(self.user_code_label)

        self.login_status_label = QLabel()
        self.login_status_label.setText("")
        self.login_status_label.setAlignment(QT_ALIGN.AlignCenter)
        verticalLayout.addWidget(self.login_status_label)

        # Collapsible group box for server config
        self.custom_server_config_group = QgsCollapsibleGroupBox()
        self.custom_server_config_group.setEnabled(True)
        self.custom_server_config_group.setTitle(self.tr("Custom server configuration"))
        self.custom_server_config_group.setCheckable(True)
        self.custom_server_config_group.setChecked(False)
        self.custom_server_config_group.setCollapsed(True)
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

        # Spacer before cancel button (shown during code verification)
        self.cancel_spacer = QSpacerItem(
            20, 20, Q_SIZE_POLICY.Minimum, Q_SIZE_POLICY.Fixed
        )
        verticalLayout.addItem(self.cancel_spacer)

        # Cancel button (shown during code verification)
        self.cancel_button = QPushButton()
        self.cancel_button.setText(self.tr("Cancel"))
        self.cancel_button.clicked.connect(self._cancel_login)
        self.cancel_button.hide()
        verticalLayout.addWidget(self.cancel_button)

    def tr(self, message):
        """Get the translation for a string using Qt translation API"""
        return QCoreApplication.translate("DialogLogin", message)

    def changeEvent(self, event):
        """ウィンドウがアクティブになった時に即座にポーリングを実行する"""
        if (
            event.type() == QEvent.ActivationChange
            and self.isActiveWindow()
            and self.auth_manager is not None
        ):
            self.auth_manager.poll_now()
        super().changeEvent(event)

    def closeEvent(self, event):
        if self.auth_manager is not None:
            self.auth_manager.cancel_auth()
        self.save_server_settings()
        super().closeEvent(event)

    def update_login_status(self):
        """Update the login status display based on stored tokens"""
        session_token = get_settings().session_token

        if session_token:
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
            # Signal was already disconnected or never connected — safe to ignore
            pass

        self._show_login_ui()

        if not success:
            QMessageBox.warning(
                self,
                self.tr("Login Error"),
                self.tr("Authentication failed: {}").format(error),
            )
            self.update_login_status()
            return

        store_setting("session_token", self.auth_manager.get_access_token())

        QgsMessageLog.logMessage(
            "Authentication successful!", LOG_CATEGORY, Qgis.Success
        )

        # Show the custom login success dialog
        success_dialog = LoginSuccess(self)
        exec_dialog(success_dialog)
        # Update the UI
        self.update_login_status()
        self.accept()

    def login(self):
        """Device Authorization Flow でログインを開始する"""
        if not self.validate_custom_server_settings():
            return
        self.save_server_settings()

        api_config = api.config.get_api_config()

        try:
            params_response = urllib.request.urlopen(
                f"{api_config.SERVER_URL}/api/_public/params"
            )
            params_data = json.loads(params_response.read().decode("utf-8"))

            # Check plugin version compatibility
            min_qgisplugin_version = params_data.get("minQgisPluginVersion")

            if min_qgisplugin_version is not None and not is_plugin_version_compatible(
                read_plugin_version(), min_qgisplugin_version
            ):
                QMessageBox.critical(
                    self,
                    self.tr("Plugin Version Error"),
                    self.tr(
                        "Please update the Kumoy plugin.\nMinimum required version: {}"
                    ).format(min_qgisplugin_version),
                )
                return
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
            QMessageBox.critical(
                self,
                self.tr("Login Error"),
                self.tr("Server error: {}").format(str(error_message)),
            )
            self.update_login_status()
            self.login_button.setEnabled(True)
            return
        except URLError as e:
            error_details = format_api_error(e)
            QgsMessageLog.logMessage(
                f"Network error: {str(error_details)}", LOG_CATEGORY, Qgis.Critical
            )
            QMessageBox.critical(
                self,
                self.tr("Login Error"),
                self.tr(
                    "Network connection error.\n"
                    "Please check your internet connection and server URL.\n\n"
                    "Details: {}"
                ).format(error_details),
            )
            self.update_login_status()
            self.login_button.setEnabled(True)
            return
        except Exception as e:
            error_text = format_api_error(e)
            QgsMessageLog.logMessage(
                f"Error during login: {error_text}", LOG_CATEGORY, Qgis.Critical
            )
            QMessageBox.critical(
                self,
                self.tr("Login Error"),
                self.tr("An error occurred while logging in: {}").format(error_text),
            )
            self.update_login_status()
            self.login_button.setEnabled(True)
            return

        self.auth_manager = AuthManager(api_config.SERVER_URL)

        self.login_status_label.setText(self.tr("Requesting device code..."))
        self.login_status_label.setStyleSheet("color: orange; font-weight: bold;")
        self.login_button.setEnabled(False)

        success, result = self.auth_manager.request_device_code()

        if not success:
            QMessageBox.warning(
                self,
                self.tr("Login Error"),
                self.tr("Failed to start authentication: {}").format(result),
            )
            self.update_login_status()
            self.login_button.setEnabled(True)
            return

        self.user_code_label.setText(result)
        self._show_code_verification_ui()

        verification_url = self.auth_manager.get_verification_url()
        QgsMessageLog.logMessage(
            f"Opening browser to: {verification_url}", LOG_CATEGORY, Qgis.Info
        )
        webbrowser.open(verification_url)

        verification_uri = self.auth_manager.verification_uri or verification_url
        self.login_status_label.setTextFormat(QT_TEXT_FORMAT_RICH)
        self.login_status_label.setText(
            self.tr(
                "Enter the code above in your browser to sign in.<br>"
                "If the browser does not open, go to:<br>"
                '<a href="{0}">{0}</a>'
            ).format(verification_uri)
        )
        self.login_status_label.setStyleSheet("")
        self.login_status_label.setTextInteractionFlags(
            QT_TEXT_INTERACTION.TextBrowserInteraction
        )
        self.login_status_label.setOpenExternalLinks(True)

        self.auth_manager.auth_completed.connect(self.on_auth_completed)
        self.auth_manager.start_polling()

    def _show_code_verification_ui(self):
        """コード確認中のUI状態に切り替える"""
        self.login_button.hide()
        self.custom_server_config_group.hide()
        self.user_code_label.show()
        self.cancel_button.show()

    def _show_login_ui(self):
        """ログイン前のUI状態に戻す"""
        self.user_code_label.hide()
        self.cancel_button.hide()
        self.login_button.show()
        self.login_button.setEnabled(True)
        self.custom_server_config_group.show()

    def _cancel_login(self):
        """認証フローをキャンセルする"""
        if self.auth_manager is not None:
            self.auth_manager.cancel_auth()
            try:
                self.auth_manager.auth_completed.disconnect(self.on_auth_completed)
            except TypeError:
                # Signal was already disconnected or never connected — safe to ignore
                pass
        self._show_login_ui()
        self.login_status_label.setText("")
        self.login_status_label.setStyleSheet("")

    def save_server_settings(self):
        use_custom_server = self.custom_server_config_group.isChecked()
        custom_server_url = self.kumoy_server_url_input.text().strip()

        store_setting("use_custom_server", "true" if use_custom_server else "false")
        store_setting("custom_server_url", custom_server_url)

    def load_server_settings(self):
        use_custom_server = get_settings().use_custom_server == "true"
        custom_server_url = get_settings().custom_server_url or ""

        self.custom_server_config_group.setChecked(use_custom_server)
        self.kumoy_server_url_input.setText(custom_server_url)

    def validate_custom_server_settings(self) -> bool:
        if not self.custom_server_config_group.isChecked():
            return True

        server_url = self.kumoy_server_url_input.text().strip()

        if server_url == "":
            QMessageBox.warning(
                self,
                self.tr("Custom Server Configuration Error"),
                self.tr(
                    "Some required settings are missing:\n{}\n\nPlease update your configuration before logging in."
                ).format(self.tr("Server URL")),
            )
            return False

        if not server_url.startswith("http"):
            QMessageBox.warning(
                self,
                self.tr("Custom Server Configuration Error"),
                self.tr("The Server URL must start with http or https."),
            )
            return False

        return True
