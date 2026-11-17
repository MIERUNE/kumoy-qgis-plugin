"""The login session token.

The token is a better-auth session token (opaque, 7-day sliding expiry). It is
stored encrypted in the QGIS authentication database instead of QSettings,
whose file sits in the profile folder that people back up, sync and share.
Encryption needs the QGIS master password; QGIS asks for it (or reads it from
the OS keychain) the first time. When encrypted storage is unavailable the
token is kept in memory only, so the user logs in again after a restart:
falling back to plain text would defeat the point.

Worker threads read the token through get_token(), which only touches the
in-memory copy; anything that may prompt runs on the main thread.
"""

from typing import Callable, List, Optional

from qgis.core import Qgis, QgsApplication, QgsMessageLog
from qgis.PyQt.QtCore import QSettings

from .constants import LOG_CATEGORY

AUTH_SETTING_KEY = "kumoy/session_token"
# Where versions up to 2.x stored the token in plain text
LEGACY_QSETTINGS_KEY = "Kumoy/session_token"

_token: Optional[str] = None
_loaded = False
# Called on the main thread after the login state changes (load, login, logout)
_listeners: List[Callable[[], None]] = []


def add_listener(fn: Callable[[], None]) -> None:
    _listeners.append(fn)


def remove_listener(fn: Callable[[], None]) -> None:
    if fn in _listeners:
        _listeners.remove(fn)


def _notify() -> None:
    for fn in list(_listeners):
        fn()


def _auth_manager():
    am = QgsApplication.authManager()
    if am is None or am.isDisabled():
        return None
    return am


def _unlock(am) -> bool:
    # Prompts on first use unless the OS keychain holds the master password
    return am.masterPasswordIsSet() or am.setMasterPassword(True)


def _persist(token: Optional[str]) -> bool:
    am = _auth_manager()
    if am is None:
        return False
    if token is None:
        if am.existsAuthSetting(AUTH_SETTING_KEY):
            am.removeAuthSetting(AUTH_SETTING_KEY)
        return True
    return _unlock(am) and am.storeAuthSetting(AUTH_SETTING_KEY, token, True)


def load() -> None:
    """Load the stored token. Main thread only: it may ask for the master password."""
    global _token, _loaded
    if _loaded:
        return
    _loaded = True

    settings = QSettings()
    legacy = settings.value(LEGACY_QSETTINGS_KEY, "")
    if legacy:
        # Remove the plain-text copy even if encrypting fails
        settings.remove(LEGACY_QSETTINGS_KEY)
        set_token(str(legacy))
        return
    _load_from_auth_db()
    _notify()


def _load_from_auth_db() -> None:
    global _token

    am = _auth_manager()
    if am is None or not am.existsAuthSetting(AUTH_SETTING_KEY):
        return
    if not _unlock(am):
        QgsMessageLog.logMessage(
            "The QGIS master password was not entered; log in to Kumoy again.",
            LOG_CATEGORY,
            Qgis.Warning,
        )
        return
    value = am.authSetting(AUTH_SETTING_KEY, None, True)
    _token = str(value) if value else None


def has_stored_token() -> bool:
    """Whether a login exists, without decrypting (never prompts)."""
    if _token:
        return True
    am = _auth_manager()
    return bool(am and am.existsAuthSetting(AUTH_SETTING_KEY))


def get_token() -> Optional[str]:
    return _token


def is_logged_in() -> bool:
    return bool(_token)


def set_token(token: str) -> bool:
    """Store the token. Returns False when it is kept in memory only."""
    global _token, _loaded
    _token = token
    _loaded = True
    persisted = _persist(token)
    if not persisted:
        QgsMessageLog.logMessage(
            "Could not store the Kumoy session in the QGIS authentication "
            "database; it is kept until QGIS closes.",
            LOG_CATEGORY,
            Qgis.Warning,
        )
    _notify()
    return persisted


def clear() -> None:
    global _token
    _token = None
    _persist(None)
    _notify()
