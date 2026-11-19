"""The login tokens.

A login is an OAuth access token (1 hour) and a refresh token (30 days, rotated
on every use) issued through the device flow; the API client refreshes on 401.
Logins made before OAuth hold a better-auth session token and no refresh token,
and keep working until that session expires. The tokens are stored encrypted in the QGIS authentication database instead of QSettings,
whose file sits in the profile folder that people back up, sync and share.
Encryption needs the QGIS master password; QGIS asks for it (or reads it from
the OS keychain) the first time. When encrypted storage is unavailable the
token is kept in memory only, so the user logs in again after a restart:
falling back to plain text would defeat the point.

Worker threads read the token through get_token(), which only touches the
in-memory copy; anything that may prompt runs on the main thread. The one
write from a worker, replace_tokens() after a refresh, stores only when the
master password is already unlocked, so it never prompts.
"""

import json
import threading
from typing import Callable, List, Optional, Tuple

from qgis.core import Qgis, QgsApplication, QgsMessageLog
from qgis.PyQt.QtCore import QSettings

from .constants import LOG_CATEGORY

AUTH_SETTING_KEY = "kumoy/session_token"
# Where versions up to 2.x stored the token in plain text
LEGACY_QSETTINGS_KEY = "Kumoy/session_token"

_token: Optional[str] = None
_refresh_token: Optional[str] = None
_loaded = False
# Serializes changes from the main thread (login, logout) and workers (refresh).
# Reentrant: storing may show the master password prompt, whose event loop can
# run another main-thread change
_lock = threading.RLock()
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


def _encode() -> Optional[str]:
    if _token is None or _refresh_token is None:
        # A pre-OAuth session token is stored as is, as those versions did
        return _token
    return json.dumps({"access_token": _token, "refresh_token": _refresh_token})


def _decode(value: str) -> Tuple[str, Optional[str]]:
    if value.startswith("{"):
        data = json.loads(value)
        return data["access_token"], data.get("refresh_token")
    return value, None


def _persist(prompt: bool = True) -> bool:
    am = _auth_manager()
    if am is None:
        return False
    value = _encode()
    if value is None:
        if am.existsAuthSetting(AUTH_SETTING_KEY):
            am.removeAuthSetting(AUTH_SETTING_KEY)
        return True
    unlocked = _unlock(am) if prompt else am.masterPasswordIsSet()
    return unlocked and am.storeAuthSetting(AUTH_SETTING_KEY, value, True)


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
    global _token, _refresh_token

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
    if value:
        _token, _refresh_token = _decode(str(value))


def has_stored_token() -> bool:
    """Whether a login exists, without decrypting (never prompts)."""
    if _token:
        return True
    am = _auth_manager()
    return bool(am and am.existsAuthSetting(AUTH_SETTING_KEY))


def get_token() -> Optional[str]:
    return _token


def get_refresh_token() -> Optional[str]:
    return _refresh_token


def is_logged_in() -> bool:
    return bool(_token)


def set_token(token: str, refresh_token: Optional[str] = None) -> bool:
    """Store a new login. Returns False when it is kept in memory only."""
    global _token, _refresh_token, _loaded
    with _lock:
        _token, _refresh_token = token, refresh_token
        _loaded = True
        persisted = _persist()
    if not persisted:
        QgsMessageLog.logMessage(
            "Could not store the Kumoy session in the QGIS authentication "
            "database; it is kept until QGIS closes.",
            LOG_CATEGORY,
            Qgis.Warning,
        )
    _notify()
    return persisted


def replace_tokens(rejected: str, token: str, refresh_token: str) -> bool:
    """Swap in refreshed tokens, unless the login changed since `rejected` was
    sent (logout, or a new login). Callable from any thread; never prompts."""
    global _token, _refresh_token
    with _lock:
        if _token != rejected:
            return False
        _token, _refresh_token = token, refresh_token
        # Kept in memory when not unlocked; the next login stores it again
        _persist(prompt=False)
        return True


def clear() -> None:
    global _token, _refresh_token
    with _lock:
        _token = _refresh_token = None
        _persist()
    _notify()
