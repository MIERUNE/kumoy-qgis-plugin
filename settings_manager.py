from dataclasses import dataclass

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QSettings

from .strato import constants


@dataclass
class UserSettings:
    id_token: str = ""
    refresh_token: str = ""
    token_expires_at: str = ""
    user_info: dict = None
    selected_organization_id: str = ""
    selected_project_id: str = ""
    use_custom_server: str = "false"
    custom_server_url: str = ""


SETTING_GROUP = "/STRATO"


def get_settings():
    # load settings from QSettings
    qsettings = QSettings()
    qsettings.beginGroup(SETTING_GROUP)

    try:
        loaded_settings = UserSettings(
            id_token=qsettings.value("id_token", ""),
            refresh_token=qsettings.value("refresh_token", ""),
            token_expires_at=qsettings.value("token_expires_at", ""),
            user_info=qsettings.value("user_info", {}),
            selected_organization_id=qsettings.value("selected_organization_id", ""),
            selected_project_id=qsettings.value("selected_project_id", ""),
            use_custom_server=qsettings.value("use_custom_server", "false"),
            custom_server_url=qsettings.value("custom_server_url", ""),
        )
    except Exception as e:
        QgsMessageLog.logMessage(
            f"Error loading settings, using default settings: {e}",
            constants.LOG_CATEGORY,
            Qgis.Warning,
        )
        # Clear potentially corrupted settings
        qsettings.remove(SETTING_GROUP)
        loaded_settings = UserSettings()

    finally:
        qsettings.endGroup()
    return loaded_settings


def store_setting(key, value):
    qsettings = QSettings()
    qsettings.beginGroup(SETTING_GROUP)
    qsettings.setValue(key, value)
    qsettings.endGroup()
