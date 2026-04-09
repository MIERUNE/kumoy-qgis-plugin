from dataclasses import dataclass

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QSettings

from .kumoy import constants
from .kumoy.local_cache.settings import reset_local_cache_settings


@dataclass
class UserSettings:
    id_token: str = ""
    selected_organization_id: str = ""
    selected_project_id: str = ""
    use_custom_server: str = "false"
    custom_server_url: str = ""


SETTING_GROUP = "/Kumoy"


def get_settings():
    # load settings from QSettings
    qsettings = QSettings()
    qsettings.beginGroup(SETTING_GROUP)

    try:
        loaded_settings = UserSettings(
            id_token=qsettings.value("id_token", ""),
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


def reset_settings():
    qsettings = QSettings()
    qsettings.beginGroup(SETTING_GROUP)
    qsettings.remove("")
    qsettings.endGroup()

    reset_local_cache_settings()
