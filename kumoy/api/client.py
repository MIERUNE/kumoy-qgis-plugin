"""Synchronous HTTP client for the Kumoy API.

Calls block the calling thread. QgsBlockingNetworkRequest is designed to be
used from worker threads, so UI code runs these calls through
kumoy.tasks.run_task instead of calling them on the main thread.
"""

import json
import threading
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from qgis.core import QgsBlockingNetworkRequest
from qgis.PyQt.QtCore import QByteArray, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest

from ...pyqt_version import Q_NETWORK_REQUEST_ATTRIBUTE, Q_NETWORK_REQUEST_HEADER
from .. import session
from . import config
from .error import AppError, UnauthorizedError, error_from_response

# One refresh at a time: refresh tokens are single use, and the server revokes
# the whole login when a used one is sent again
_refresh_lock = threading.Lock()


def server_url() -> str:
    return config.get_api_config().SERVER_URL


def _decode(content: QByteArray) -> Any:
    if content is None or content.isEmpty():
        return None
    text = bytes(content.data()).decode("utf-8", errors="replace").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        # Proxies and load balancers answer HTML on errors
        return None


def request(
    method: str,
    path: str,
    data: Any = None,
    params: Optional[Dict[str, Any]] = None,
    auth: bool = True,
    headers: Optional[Dict[str, str]] = None,
    response_headers: Optional[Dict[str, str]] = None,
    form: Optional[Dict[str, str]] = None,
    _refresh_on_401: bool = True,
) -> Any:
    """Send a request to `{server}{path}` and return the decoded JSON body.

    `path` includes the `/api` prefix. `form` sends a form-urlencoded body
    instead of `data` as JSON (the OAuth endpoints require it). Raises an
    AppError subclass on any failure, chosen by HTTP status (see error.py).
    When `response_headers` is given it is filled with the reply headers
    (lower-case names). On 401 the login is refreshed and the request sent once
    more.
    """
    url = f"{server_url()}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    req = QNetworkRequest(QUrl(url))
    for key, value in (headers or {}).items():
        req.setRawHeader(key.encode("utf-8"), value.encode("utf-8"))
    token = session.get_token() if auth else None
    if auth:
        if not token:
            error = UnauthorizedError("Unauthorized", "Not logged in")
            error.rejected_token = token or ""
            raise error
        req.setRawHeader(b"Authorization", f"Bearer {token}".encode("utf-8"))

    body = QByteArray()
    if form is not None:
        req.setHeader(
            Q_NETWORK_REQUEST_HEADER.ContentTypeHeader,
            "application/x-www-form-urlencoded",
        )
        body = QByteArray(urlencode(form).encode("utf-8"))
    elif data is not None:
        req.setHeader(Q_NETWORK_REQUEST_HEADER.ContentTypeHeader, "application/json")
        body = QByteArray(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    blocking = QgsBlockingNetworkRequest()
    if method == "GET":
        err = blocking.get(req, forceRefresh=True)
    elif method == "POST":
        err = blocking.post(req, body)
    elif method == "PUT":
        err = blocking.put(req, body)
    elif method == "DELETE":
        err = blocking.deleteResource(req)
    else:
        raise ValueError(f"Unsupported method: {method}")

    reply = blocking.reply()
    if response_headers is not None:
        # QgsNetworkReplyContent has no rawHeaderPairs() (QNetworkReply does)
        for name in reply.rawHeaderList():
            key = bytes(name).decode("latin-1").lower()
            response_headers[key] = bytes(reply.rawHeader(name)).decode("latin-1")
    status = reply.attribute(Q_NETWORK_REQUEST_ATTRIBUTE.HttpStatusCodeAttribute)
    status = int(status) if status is not None else None
    content = _decode(reply.content())

    if err == QgsBlockingNetworkRequest.NoError and status is not None and status < 400:
        return content
    error = error_from_response(status, content, blocking.errorMessage())
    if isinstance(error, UnauthorizedError) and token and _refresh_on_401:
        if _refreshed_token(token) is not None:
            return request(
                method,
                path,
                data,
                params,
                auth,
                headers,
                response_headers,
                form,
                _refresh_on_401=False,
            )
    if isinstance(error, UnauthorizedError):
        # Lets the 401 handler tell this login from one made since
        error.rejected_token = token or ""
    raise error


def _refreshed_token(rejected: str) -> Optional[str]:
    """A token to retry with after `rejected` got a 401, or None when the login
    cannot be renewed (the caller then reports the 401, which logs out)."""
    from . import auth  # auth imports this module

    with _refresh_lock:
        current = session.get_token()
        if current != rejected:
            # Another request refreshed meanwhile, or the login changed
            return current
        refresh_token = session.get_refresh_token()
        if not refresh_token:
            return None  # a login made before OAuth
        try:
            tokens = auth.refresh(refresh_token)
        except AppError as e:
            if e.status in (400, 401):
                return None  # expired or revoked: log in again
            # Offline or a server error: report that rather than logging out
            raise
        if not session.replace_tokens(
            rejected, tokens.access_token, tokens.refresh_token
        ):
            return session.get_token()
        return tokens.access_token


def get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    return request("GET", f"/api{path}", params=params)


def post(path: str, data: Any = None) -> Any:
    return request("POST", f"/api{path}", data=data if data is not None else {})


def put(path: str, data: Any) -> Any:
    return request("PUT", f"/api{path}", data=data)


def delete(path: str) -> Any:
    return request("DELETE", f"/api{path}")
