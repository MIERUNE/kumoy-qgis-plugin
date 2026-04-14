import json
from typing import Any, Dict, Optional

from qgis.core import QgsBlockingNetworkRequest
from qgis.PyQt.QtCore import QByteArray, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest

from ...pyqt_version import Q_NETWORK_REQUEST_HEADER, Q_NETWORK_REQUEST_HTTP_STATUS_ATTR
from ..get_token import get_token
from . import config as api_config
from . import error as api_error


def _handle_response(
    blocking_request: QgsBlockingNetworkRequest,
    err: int,
) -> Any:
    """Parse reply content and raise on network or API error"""
    reply = blocking_request.reply()
    http_status = int(reply.attribute(Q_NETWORK_REQUEST_HTTP_STATUS_ATTR) or 0)

    raw = reply.content()
    if not raw or raw.isEmpty():
        content = {}
    else:
        text = str(raw.data(), "utf-8")
        if not text.strip():
            content = {}
        else:
            try:
                content = json.loads(text)
            except json.JSONDecodeError:
                # Case of HTML response from proxies (e.g., Cloudflare authentication redirects)
                status_hint = (
                    f"HTTP {http_status}" if http_status else "no HTTP status"
                )
                if text.lstrip().startswith("<"):
                    if http_status in (502, 503, 504):
                        raise api_error.UnderMaintenanceError(
                            "Under Maintenance", f"HTML response ({status_hint})"
                        )
                    raise api_error.UnauthorizedError(
                        "Unauthorized", f"HTML response ({status_hint})"
                    )
                raise api_error.AppError(
                    "Unexpected non-JSON response from server", status_hint
                )

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
        """
        Args:
            endpoint (str): _description_
            params (Optional[Dict], optional): _description_. Defaults to None.

        Returns:
            dict: {"content": dict, "error": None} or {"content": None, "error": str}
        """
        _api_config = api_config.get_api_config()
        # Build URL with query parameters if provided
        url = f"{_api_config.SERVER_URL}/api{endpoint}"
        if params:
            query_items = []
            for key, value in params.items():
                query_items.append(f"{key}={value}")
            url = f"{url}?{'&'.join(query_items)}"

        # Create request with authorization header
        req = QNetworkRequest(QUrl(url))
        token = get_token()

        if not token:
            return {"content": None, "error": "Authentication Error"}

        req.setRawHeader(
            "Authorization".encode("utf-8"),
            f"Bearer {token}".encode("utf-8"),
        )

        # Execute request
        blocking_request = QgsBlockingNetworkRequest()
        err = blocking_request.get(req, forceRefresh=True)
        return _handle_response(blocking_request, err)

    @staticmethod
    def post(endpoint: str, data: Any) -> Any:
        """Make POST request to API endpoint

        Args:
            endpoint (str): API endpoint
            data (Any): Data to send in the request body

        Returns:
            dict: {"content": dict, "error": None} or {"content": None, "error": str}
        """
        _api_config = api_config.get_api_config()
        url = f"{_api_config.SERVER_URL}/api{endpoint}"

        # Create request with authorization header
        req = QNetworkRequest(QUrl(url))
        token = get_token()

        if not token:
            return {"content": None, "error": "Authentication Error"}

        req.setRawHeader(
            "Authorization".encode("utf-8"),
            f"Bearer {token}".encode("utf-8"),
        )
        req.setHeader(Q_NETWORK_REQUEST_HEADER.ContentTypeHeader, "application/json")

        # Use json.dumps to preserve dictionary order
        json_data = json.dumps(data, ensure_ascii=False)
        byte_array = QByteArray(json_data.encode("utf-8"))

        # Execute request
        blocking_request = QgsBlockingNetworkRequest()
        err = blocking_request.post(req, byte_array)
        return _handle_response(blocking_request, err)

    @staticmethod
    def put(endpoint: str, data: Any) -> Any:
        """Make PUT request to API endpoint

        Args:
            endpoint (str): API endpoint
            data (Any): Data to send in the request body

        Returns:
            dict: {"content": dict, "error": None} or {"content": None, "error": str}
        """
        _api_config = api_config.get_api_config()
        url = f"{_api_config.SERVER_URL}/api{endpoint}"

        # Create request with authorization header
        req = QNetworkRequest(QUrl(url))
        token = get_token()

        if not token:
            return {"content": None, "error": "Authentication Error"}

        req.setRawHeader(
            "Authorization".encode("utf-8"),
            f"Bearer {token}".encode("utf-8"),
        )
        req.setHeader(Q_NETWORK_REQUEST_HEADER.ContentTypeHeader, "application/json")

        # Use json.dumps to preserve dictionary order
        json_data = json.dumps(data, ensure_ascii=False)
        byte_array = QByteArray(json_data.encode("utf-8"))

        # Execute request
        blocking_request = QgsBlockingNetworkRequest()
        err = blocking_request.put(req, byte_array)
        return _handle_response(blocking_request, err)

    @staticmethod
    def delete(endpoint: str) -> Any:
        """Make DELETE request to API endpoint

        Args:
            endpoint (str): API endpoint

        Returns:
            dict: {"content": dict, "error": None} or {"content": None, "error": str}
        """
        _api_config = api_config.get_api_config()
        url = f"{_api_config.SERVER_URL}/api{endpoint}"

        # Create request with authorization header
        req = QNetworkRequest(QUrl(url))
        token = get_token()

        if not token:
            return {"content": None, "error": "Authentication Error"}

        req.setRawHeader(
            "Authorization".encode("utf-8"),
            f"Bearer {token}".encode("utf-8"),
        )

        # Execute request
        blocking_request = QgsBlockingNetworkRequest()
        err = blocking_request.deleteResource(req)
        return _handle_response(blocking_request, err)
