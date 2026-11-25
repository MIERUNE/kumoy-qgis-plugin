import json
import threading
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

from qgis.core import Qgis, QgsBlockingNetworkRequest, QgsMessageLog
from qgis.PyQt.QtCore import QByteArray, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest

from ...pyqt_version import Q_NETWORK_REQUEST_ATTRIBUTE, Q_NETWORK_REQUEST_HEADER
from ..constants import LOG_CATEGORY, OAUTH_CLIENT_ID
from ..get_token import get_token
from ..settings_manager import get_settings, store_setting
from . import config as api_config
from . import error as api_error

# Refresh tokens rotate and the server revokes the whole family when a used one
# is replayed, so concurrent refreshes (browser + processing threads) must be
# serialized.
_refresh_lock = threading.Lock()


def handle_blocking_reply(content: QByteArray) -> Any:
    """Handle QgsBlockingNetworkRequest reply and convert to Python dict"""
    if not content or content.isEmpty():
        return {}
    text = str(content.data(), "utf-8")
    if not text.strip():
        return {}

    return json.loads(text)


def _status_code(blocking_request: QgsBlockingNetworkRequest) -> Optional[int]:
    return blocking_request.reply().attribute(
        Q_NETWORK_REQUEST_ATTRIBUTE.HttpStatusCodeAttribute
    )


def _process_response(blocking_request: QgsBlockingNetworkRequest, err: int) -> Any:
    """Inspect the reply, raise typed errors on failure, otherwise return content."""
    status_code = _status_code(blocking_request)
    content = handle_blocking_reply(blocking_request.reply().content())

    if status_code in (401, 403):
        message = "Unauthorized"
        detail = ""
        if isinstance(content, dict):
            detail = content.get("error", "") or content.get("message", "")
        raise api_error.UnauthorizedError(message, detail)

    if err != QgsBlockingNetworkRequest.NoError:
        if not content:
            error_message = blocking_request.errorMessage()
            api_error.raise_error({"message": error_message, "error": ""})
        else:
            api_error.raise_error(content)

    return content


def _send(
    method: str, url: str, token: str, data: Any
) -> Tuple[QgsBlockingNetworkRequest, int]:
    req = QNetworkRequest(QUrl(url))
    req.setRawHeader(b"Authorization", f"Bearer {token}".encode("utf-8"))

    blocking_request = QgsBlockingNetworkRequest()
    if method == "GET":
        err = blocking_request.get(req, forceRefresh=True)
    elif method == "DELETE":
        err = blocking_request.deleteResource(req)
    else:
        req.setHeader(Q_NETWORK_REQUEST_HEADER.ContentTypeHeader, "application/json")
        body = QByteArray(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        if method == "POST":
            err = blocking_request.post(req, body)
        else:
            err = blocking_request.put(req, body)
    return blocking_request, err


def _request(method: str, endpoint: str, data: Any = None) -> Any:
    url = f"{api_config.get_api_config().SERVER_URL}/api{endpoint}"

    token = get_token()
    if not token:
        raise api_error.UnauthorizedError("Unauthorized", "No session token")

    blocking_request, err = _send(method, url, token, data)
    # Access tokens live for an hour; refresh once and retry instead of
    # treating expiry as a logout.
    if _status_code(blocking_request) == 401 and _refresh_access_token(token):
        blocking_request, err = _send(method, url, get_token(), data)
    return _process_response(blocking_request, err)


def _post_auth_form(path: str, fields: Dict[str, str]) -> Tuple[Optional[int], Any]:
    """POST form-urlencoded to a Better Auth OAuth endpoint (RFC 6749 style)."""
    server_url = api_config.get_api_config().SERVER_URL
    req = QNetworkRequest(QUrl(f"{server_url}/api/auth{path}"))
    req.setHeader(
        Q_NETWORK_REQUEST_HEADER.ContentTypeHeader,
        "application/x-www-form-urlencoded",
    )
    req.setRawHeader(b"Origin", server_url.encode("utf-8"))

    blocking_request = QgsBlockingNetworkRequest()
    blocking_request.post(req, QByteArray(urlencode(fields).encode("utf-8")))
    status_code = _status_code(blocking_request)
    if status_code is None or status_code >= 500:
        # Network/server failure: surface it as an error, not as a logout
        api_error.raise_error({"message": blocking_request.errorMessage(), "error": ""})
    try:
        content = handle_blocking_reply(blocking_request.reply().content())
    except ValueError:
        content = {}
    return status_code, content


def _refresh_access_token(failed_token: str) -> bool:
    """Rotate tokens. Returns True when a newer access token is stored."""
    with _refresh_lock:
        settings = get_settings()
        if settings.session_token != failed_token:
            # Another thread refreshed (or logged out) while we waited
            return bool(settings.session_token)
        if not settings.refresh_token:
            # Legacy session token from the pre-OAuth plugin: nothing to refresh
            return False

        status_code, content = _post_auth_form(
            "/oauth2/token",
            {
                "grant_type": "refresh_token",
                "refresh_token": settings.refresh_token,
                "client_id": OAUTH_CLIENT_ID,
            },
        )
        if not isinstance(content, dict):
            content = {}
        access_token = content.get("access_token")
        refresh_token = content.get("refresh_token")
        if status_code == 200 and access_token and refresh_token:
            store_setting("session_token", access_token)
            store_setting("refresh_token", refresh_token)
            return True

        # invalid_grant (expired, revoked or replayed): only a new login helps
        QgsMessageLog.logMessage(
            f"Token refresh failed: status={status_code}, body={content}",
            LOG_CATEGORY,
            Qgis.Warning,
        )
        store_setting("refresh_token", "")
        return False


def revoke_refresh_token() -> None:
    """Revoke the stored refresh token (and the access tokens issued from it).

    Best effort: callers clear the local tokens regardless, and an unrevoked
    token still expires on its own.
    """
    refresh_token = get_settings().refresh_token
    if not refresh_token:
        return
    try:
        _post_auth_form(
            "/oauth2/revoke",
            {
                "token": refresh_token,
                "token_type_hint": "refresh_token",
                "client_id": OAUTH_CLIENT_ID,
            },
        )
    except Exception as e:
        QgsMessageLog.logMessage(
            f"Failed to revoke refresh token: {api_error.format_api_error(e)}",
            LOG_CATEGORY,
            Qgis.Warning,
        )


class ApiClient:
    """Base API client for Kumoy backend"""

    @staticmethod
    def get(endpoint: str, params: Optional[Dict] = None) -> Any:
        if params:
            query_items = [f"{key}={value}" for key, value in params.items()]
            endpoint = f"{endpoint}?{'&'.join(query_items)}"
        return _request("GET", endpoint)

    @staticmethod
    def post(endpoint: str, data: Any) -> Any:
        return _request("POST", endpoint, data)

    @staticmethod
    def put(endpoint: str, data: Any) -> Any:
        return _request("PUT", endpoint, data)

    @staticmethod
    def delete(endpoint: str) -> Any:
        return _request("DELETE", endpoint)
