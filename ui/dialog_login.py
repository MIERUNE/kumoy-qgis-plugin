import webbrowser

from qgis.core import Qgis, QgsMessageLog
from qgis.gui import QgsCollapsibleGroupBox
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
    QWidget,
)
from qgis.utils import iface

from .. import i18n
from ..kumoy import session, settings_manager
from ..kumoy.auth_manager import DeviceLogin
from ..kumoy.basemap import add_xyz_connections
from ..kumoy.constants import LOG_CATEGORY
from ..plugin_version import read_plugin_version
from ..pyqt_version import (
    Q_SIZE_POLICY,
    QT_ALIGN,
    QT_EVENT_TYPE,
    QT_TEXT_FORMAT_RICH,
    QT_TEXT_INTERACTION,
    exec_dialog,
)
from . import account_actions
from .dialog_project_select import open_project_dialog
from .error_handler import push_success, refresh_kumoy_browser
from .icons import MAIN_ICON


def open_login_dialog() -> None:
    """Log in, then let the user pick a project (used by the menu, the
    Browser and the session-expired notice)."""
    # No parent: a child of the main window would never be freed
    dialog = DialogLogin()
    if not exec_dialog(dialog):
        return

    push_success(i18n.tr("You are now logged in to Kumoy."))
    if not dialog.persisted and iface is not None:
        iface.messageBar().pushMessage(
            i18n.tr("Kumoy"),
            i18n.tr(
                "Your login could not be stored in the QGIS authentication "
                "database, so you will need to log in again after restarting QGIS."
            ),
            Qgis.Warning,
            0,
        )
    account_actions.check_plugin_version()
    refresh_kumoy_browser()
    open_project_dialog()


class DialogLogin(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        # False when the token is kept in memory only (see session.set_token)
        self.persisted = True
        self._login = DeviceLogin(self)
        self._login.code_received.connect(self._on_code_received)
        self._login.succeeded.connect(self._on_succeeded)
        self._login.failed.connect(self._on_failed)
        # Esc and the close button both end in finished(); stop polling then
        self.finished.connect(self._login.cancel)
        self.setupUi()
        self.load_server_settings()
        self.update_login_status()

    def setupUi(self):
        self.setObjectName("Dialog")
        self.resize(400, 400)
        self.setMinimumSize(400, 0)
        self.setWindowTitle(i18n.tr("Authentication"))
        self.setContentsMargins(10, 10, 10, 10)

        verticalLayout = QVBoxLayout(self)

        version_label = QLabel(read_plugin_version())
        version_label.setAlignment(QT_ALIGN.AlignRight)
        verticalLayout.addWidget(version_label)

        logo_layout = QHBoxLayout()
        logo_icon_label = QLabel()
        logo_icon_label.setSizePolicy(Q_SIZE_POLICY.Fixed, Q_SIZE_POLICY.Fixed)
        logo_icon_label.setPixmap(MAIN_ICON.pixmap(128, 128))
        logo_icon_label.setScaledContents(True)
        logo_icon_label.setAlignment(QT_ALIGN.AlignCenter)
        logo_layout.addWidget(logo_icon_label)
        verticalLayout.addLayout(logo_layout)

        verticalLayout.addItem(
            QSpacerItem(20, 20, Q_SIZE_POLICY.Minimum, Q_SIZE_POLICY.Fixed)
        )

        welcome_label = QLabel(
            i18n.tr(
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
        welcome_label.setContentsMargins(0, 20, 0, 40)
        welcome_label.setAlignment(QT_ALIGN.AlignCenter)
        welcome_label.setOpenExternalLinks(True)
        verticalLayout.addWidget(welcome_label)

        self.login_button = QPushButton(i18n.tr("Login"))
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
        self.login_status_label.setAlignment(QT_ALIGN.AlignCenter)
        self.login_status_label.setWordWrap(True)
        verticalLayout.addWidget(self.login_status_label)

        self.custom_server_config_group = QgsCollapsibleGroupBox()
        self.custom_server_config_group.setTitle(i18n.tr("Custom server configuration"))
        self.custom_server_config_group.setCheckable(True)
        self.custom_server_config_group.setChecked(False)
        self.custom_server_config_group.setCollapsed(True)
        self.custom_server_config_group.setSaveCheckedState(False)
        gridLayout = QGridLayout(self.custom_server_config_group)
        gridLayout.addWidget(QLabel(i18n.tr("Server URL")), 1, 0)
        self.kumoy_server_url_input = QLineEdit()
        gridLayout.addWidget(self.kumoy_server_url_input, 1, 1)
        verticalLayout.addWidget(self.custom_server_config_group)

        self.cancel_spacer = QWidget()
        self.cancel_spacer.setFixedHeight(20)
        self.cancel_spacer.hide()
        verticalLayout.addWidget(self.cancel_spacer)

        self.cancel_button = QPushButton(i18n.tr("Cancel"))
        self.cancel_button.clicked.connect(self._cancel_login)
        self.cancel_button.hide()
        verticalLayout.addWidget(self.cancel_button)

    def changeEvent(self, event):
        # Coming back from the browser usually means the user just approved
        if event.type() == QT_EVENT_TYPE.ActivationChange and self.isActiveWindow():
            self._login.poll_now()
        super().changeEvent(event)

    def closeEvent(self, event):
        self.save_server_settings()
        super().closeEvent(event)

    def _set_status(self, text: str, style: str = "") -> None:
        self.login_status_label.setText(text)
        self.login_status_label.setStyleSheet(style)

    def update_login_status(self):
        if session.is_logged_in():
            self._set_status(
                i18n.tr("Logged in"),
                "color: green; font-weight: bold; font-size: 24px;",
            )
        else:
            self._set_status("")

    def login(self):
        """Start the OAuth device authorization flow."""
        if not self.validate_custom_server_settings():
            return
        self.save_server_settings()
        self.login_button.setEnabled(False)
        self.custom_server_config_group.setEnabled(False)
        self._set_status(
            i18n.tr("Requesting device code..."), "color: orange; font-weight: bold;"
        )
        self._login.start()

    def _on_code_received(self, user_code: str, verification_url: str) -> None:
        self.user_code_label.setText(user_code)
        self._show_code_verification_ui()
        QgsMessageLog.logMessage(
            f"Opening browser to: {verification_url}", LOG_CATEGORY, Qgis.Info
        )
        webbrowser.open(verification_url)
        self.login_status_label.setTextFormat(QT_TEXT_FORMAT_RICH)
        self.login_status_label.setTextInteractionFlags(
            QT_TEXT_INTERACTION.TextBrowserInteraction
        )
        self.login_status_label.setOpenExternalLinks(True)
        self._set_status(
            i18n.tr(
                "Enter the code above in your browser to sign in.<br>"
                "If the browser does not open, go to:<br>"
                '<a href="{0}">{0}</a>'
            ).format(verification_url)
        )

    def _on_succeeded(self, token: str) -> None:
        self.persisted = session.set_token(token)
        add_xyz_connections()
        if iface is not None:
            iface.reloadConnections()
        QgsMessageLog.logMessage("Authentication successful!", LOG_CATEGORY, Qgis.Info)
        self.accept()

    def _on_failed(self, message: str) -> None:
        self._show_login_ui()
        self.update_login_status()
        QMessageBox.warning(self, i18n.tr("Login Error"), message)

    def _show_code_verification_ui(self):
        self.login_button.hide()
        self.custom_server_config_group.hide()
        self.user_code_label.show()
        self.cancel_spacer.show()
        self.cancel_button.show()

    def _show_login_ui(self):
        self.user_code_label.hide()
        self.cancel_spacer.hide()
        self.cancel_button.hide()
        self.login_button.show()
        self.login_button.setEnabled(True)
        self.custom_server_config_group.setEnabled(True)
        self.custom_server_config_group.show()

    def _cancel_login(self):
        self._login.cancel()
        self._show_login_ui()
        self.update_login_status()

    def save_server_settings(self):
        settings_manager.set_custom_server(
            self.custom_server_config_group.isChecked(),
            self.kumoy_server_url_input.text(),
        )

    def load_server_settings(self):
        self.custom_server_config_group.setChecked(
            settings_manager.get("use_custom_server", "false") == "true"
        )
        self.kumoy_server_url_input.setText(settings_manager.get("custom_server_url"))

    def validate_custom_server_settings(self) -> bool:
        if not self.custom_server_config_group.isChecked():
            return True

        server_url = self.kumoy_server_url_input.text().strip()
        if not server_url:
            QMessageBox.warning(
                self,
                i18n.tr("Custom Server Configuration Error"),
                i18n.tr(
                    "Some required settings are missing:\n{}\n\nPlease update your configuration before logging in."
                ).format(i18n.tr("Server URL")),
            )
            return False
        if not server_url.startswith(("http://", "https://")):
            QMessageBox.warning(
                self,
                i18n.tr("Custom Server Configuration Error"),
                i18n.tr("The Server URL must start with http or https."),
            )
            return False
        return True
