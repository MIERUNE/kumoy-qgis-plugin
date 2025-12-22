from qgis.PyQt.QtCore import QSettings

SETTING_GROUP = "/Kumoy/local_cache"


def get_last_updated(vector_id: str) -> str:
    """
    Get the last updated timestamp for a vector ID from settings.
    Returns None if not found.
    """
    qsettings = QSettings()
    qsettings.beginGroup(SETTING_GROUP)
    value = qsettings.value(vector_id)
    qsettings.endGroup()
    return value


def store_last_updated(vector_id: str, timestamp: str):
    """
    Store the last updated timestamp for a vector ID in settings.
    """
    qsettings = QSettings()
    qsettings.beginGroup(SETTING_GROUP)
    qsettings.setValue(vector_id, timestamp)
    qsettings.endGroup()


def delete_last_updated(vector_id: str):
    """
    Delete the last updated timestamp for a vector ID from settings.
    """
    qsettings = QSettings()
    qsettings.beginGroup(SETTING_GROUP)
    qsettings.remove(vector_id)
    qsettings.endGroup()


def reset_local_cache_settings():
    """
    Reset local cache settings.
    """
    qsettings = QSettings()
    qsettings.beginGroup(SETTING_GROUP)
    qsettings.remove("")
    qsettings.endGroup()
