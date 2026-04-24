import json
from typing import Any, Dict, Optional

from qgis.core import QgsBlockingNetworkRequest
from qgis.PyQt.QtCore import QByteArray, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest

from ...pyqt_version import Q_NETWORK_REQUEST_HEADER
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
        content = handle_blocking_reply(blocking_request.reply().content())
        if err != QgsBlockingNetworkRequest.NoError:
            # Handle empty content when network error occurs
            if not content:
                error_message = blocking_request.errorMessage()
                api_error.raise_error({"message": error_message, "error": ""})
            else:
                api_error.raise_error(content)

        return content

    @staticmethod
    def get_public(endpoint: str) -> Any:
        """Make GET request to a public (unauthenticated) API endpoint.

        Validates the URL scheme and distinguishes network errors from
        HTTP 4xx/5xx server errors.

        Args:
            endpoint (str): API endpoint (e.g. "/_public/params")

        Returns:
            dict: Parsed JSON response body

        Raises:
            ValueError: If the URL scheme is not http or https
            AppError: If the server returns a 4xx/5xx error
        """
        _api_config = api_config.get_api_config()
        qurl = QUrl(f"{_api_config.SERVER_URL}/api{endpoint}")
        if qurl.scheme() not in ("http", "https"):
            raise ValueError(f"Unexpected URL scheme: {qurl.scheme()}")

        req = QNetworkRequest(qurl)
        blocking_request = QgsBlockingNetworkRequest()
        err = blocking_request.get(req, forceRefresh=True)

        reply = blocking_request.reply()
        status_code = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        content = handle_blocking_reply(reply.content())

        if err != QgsBlockingNetworkRequest.NoError:
            if status_code is not None:
                # HTTP error (4xx/5xx): body may contain error details
                if content:
                    api_error.raise_error(content)
                api_error.raise_error(
                    {"message": f"Server error (HTTP {status_code})", "error": ""}
                )
            else:
                # Network-level error (no HTTP response)
                api_error.raise_error(
                    {"message": blocking_request.errorMessage(), "error": ""}
                )

        return content

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
        content = handle_blocking_reply(blocking_request.reply().content())
        if err != QgsBlockingNetworkRequest.NoError:
            if not content:
                error_message = blocking_request.errorMessage()
                api_error.raise_error({"message": error_message, "error": ""})
            else:
                api_error.raise_error(content)

        return content

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
        content = handle_blocking_reply(blocking_request.reply().content())
        if err != QgsBlockingNetworkRequest.NoError:
            if not content:
                error_message = blocking_request.errorMessage()
                api_error.raise_error({"message": error_message, "error": ""})
            else:
                api_error.raise_error(content)

        return content

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
        content = handle_blocking_reply(blocking_request.reply().content())
        if err != QgsBlockingNetworkRequest.NoError:
            if not content:
                error_message = blocking_request.errorMessage()
                api_error.raise_error({"message": error_message})
            else:
                api_error.raise_error(content)

        return content
