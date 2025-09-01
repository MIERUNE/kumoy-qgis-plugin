import json
from typing import Any, Dict, Optional

from qgis.core import QgsBlockingNetworkRequest
from qgis.PyQt.QtCore import QByteArray, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest

from ..get_token import get_token
from . import config as api_config
from . import error as api_error


def handle_blocking_reply(content: QByteArray) -> dict:
    """Handle QgsBlockingNetworkRequest reply and convert to Python dict"""
    if not content or content.isEmpty():
        return {}
    text = str(content.data(), "utf-8")
    if not text.strip():
        return {}
    return json.loads(text)


class ApiClient:
    """Base API client for STRATO backend"""

    @staticmethod
    def get(endpoint: str, params: Optional[Dict] = None) -> dict:
        """
        Args:
            endpoint (str): _description_
            params (Optional[Dict], optional): _description_. Defaults to None.

        Returns:
            dict: {"content": dict, "error": None} or {"content": None, "error": str}
        """
        _api_config = api_config.get_api_config()
        # Build URL with query parameters if provided
        url = f"{_api_config.API_URL}{endpoint}"
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
        err = blocking_request.get(req)
        content = handle_blocking_reply(blocking_request.reply().content())
        if err != QgsBlockingNetworkRequest.NoError:
            api_error.raise_error(content)

        return content

    @staticmethod
    def post(endpoint: str, data: Any) -> dict:
        """Make POST request to API endpoint

        Args:
            endpoint (str): API endpoint
            data (Any): Data to send in the request body

        Returns:
            dict: {"content": dict, "error": None} or {"content": None, "error": str}
        """
        _api_config = api_config.get_api_config()
        url = f"{_api_config.API_URL}{endpoint}"

        # Create request with authorization header
        req = QNetworkRequest(QUrl(url))
        token = get_token()

        if not token:
            return {"content": None, "error": "Authentication Error"}

        req.setRawHeader(
            "Authorization".encode("utf-8"),
            f"Bearer {token}".encode("utf-8"),
        )
        req.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")

        # Use json.dumps to preserve dictionary order
        json_data = json.dumps(data, ensure_ascii=False)
        byte_array = QByteArray(json_data.encode("utf-8"))

        # Execute request
        blocking_request = QgsBlockingNetworkRequest()
        err = blocking_request.post(req, byte_array)
        content = handle_blocking_reply(blocking_request.reply().content())
        if err != QgsBlockingNetworkRequest.NoError:
            api_error.raise_error(content)

        return content

    @staticmethod
    def put(endpoint: str, data: Any) -> dict:
        """Make PUT request to API endpoint

        Args:
            endpoint (str): API endpoint
            data (Any): Data to send in the request body

        Returns:
            dict: {"content": dict, "error": None} or {"content": None, "error": str}
        """
        _api_config = api_config.get_api_config()
        url = f"{_api_config.API_URL}{endpoint}"

        # Create request with authorization header
        req = QNetworkRequest(QUrl(url))
        token = get_token()

        if not token:
            return {"content": None, "error": "Authentication Error"}

        req.setRawHeader(
            "Authorization".encode("utf-8"),
            f"Bearer {token}".encode("utf-8"),
        )
        req.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")

        # Use json.dumps to preserve dictionary order
        json_data = json.dumps(data, ensure_ascii=False)
        byte_array = QByteArray(json_data.encode("utf-8"))

        # Execute request
        blocking_request = QgsBlockingNetworkRequest()
        err = blocking_request.put(req, byte_array)
        content = handle_blocking_reply(blocking_request.reply().content())
        if err != QgsBlockingNetworkRequest.NoError:
            api_error.raise_error(content)

        return content

    @staticmethod
    def delete(endpoint: str) -> dict:
        """Make DELETE request to API endpoint

        Args:
            endpoint (str): API endpoint

        Returns:
            dict: {"content": dict, "error": None} or {"content": None, "error": str}
        """
        _api_config = api_config.get_api_config()
        url = f"{_api_config.API_URL}{endpoint}"

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
            api_error.raise_error(content)

        return content
