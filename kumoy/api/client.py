import json
from typing import Any, Dict, Optional

from qgis.core import QgsBlockingNetworkRequest
from qgis.PyQt.QtCore import QByteArray, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest

from ...pyqt_version import Q_NETWORK_REQUEST_ATTRIBUTE, Q_NETWORK_REQUEST_HEADER
from ..get_token import get_token
from . import config as api_config
from . import error as api_error


def handle_blocking_reply(content: QByteArray) -> Any:
    """Handle QgsBlockingNetworkRequest reply and convert to Python dict"""
    if not content or content.isEmpty():
        return {}
    text = str(content.data(), "utf-8")
    if not text.strip():
        return {}

    return json.loads(text)


def _build_request(url: str) -> QNetworkRequest:
    """Build an authorized QNetworkRequest. Raises UnauthorizedError if no token."""
    token = get_token()
    if not token:
        raise api_error.UnauthorizedError("Unauthorized", "No session token")

    req = QNetworkRequest(QUrl(url))
    req.setRawHeader(
        "Authorization".encode("utf-8"),
        f"Bearer {token}".encode("utf-8"),
    )
    return req


def _process_response(blocking_request: QgsBlockingNetworkRequest, err: int) -> Any:
    """Inspect the reply, raise typed errors on failure, otherwise return content."""
    reply = blocking_request.reply()
    status_code = reply.attribute(Q_NETWORK_REQUEST_ATTRIBUTE.HttpStatusCodeAttribute)
    content = handle_blocking_reply(reply.content())

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


class ApiClient:
    """Base API client for Kumoy backend"""

    @staticmethod
    def get(endpoint: str, params: Optional[Dict] = None) -> Any:
        _api_config = api_config.get_api_config()
        url = f"{_api_config.SERVER_URL}/api{endpoint}"
        if params:
            query_items = [f"{key}={value}" for key, value in params.items()]
            url = f"{url}?{'&'.join(query_items)}"

        req = _build_request(url)

        blocking_request = QgsBlockingNetworkRequest()
        err = blocking_request.get(req, forceRefresh=True)
        return _process_response(blocking_request, err)

    @staticmethod
    def post(endpoint: str, data: Any) -> Any:
        _api_config = api_config.get_api_config()
        url = f"{_api_config.SERVER_URL}/api{endpoint}"

        req = _build_request(url)
        req.setHeader(Q_NETWORK_REQUEST_HEADER.ContentTypeHeader, "application/json")

        json_data = json.dumps(data, ensure_ascii=False)
        byte_array = QByteArray(json_data.encode("utf-8"))

        blocking_request = QgsBlockingNetworkRequest()
        err = blocking_request.post(req, byte_array)
        return _process_response(blocking_request, err)

    @staticmethod
    def put(endpoint: str, data: Any) -> Any:
        _api_config = api_config.get_api_config()
        url = f"{_api_config.SERVER_URL}/api{endpoint}"

        req = _build_request(url)
        req.setHeader(Q_NETWORK_REQUEST_HEADER.ContentTypeHeader, "application/json")

        json_data = json.dumps(data, ensure_ascii=False)
        byte_array = QByteArray(json_data.encode("utf-8"))

        blocking_request = QgsBlockingNetworkRequest()
        err = blocking_request.put(req, byte_array)
        return _process_response(blocking_request, err)

    @staticmethod
    def delete(endpoint: str) -> Any:
        _api_config = api_config.get_api_config()
        url = f"{_api_config.SERVER_URL}/api{endpoint}"

        req = _build_request(url)

        blocking_request = QgsBlockingNetworkRequest()
        err = blocking_request.deleteResource(req)
        return _process_response(blocking_request, err)
