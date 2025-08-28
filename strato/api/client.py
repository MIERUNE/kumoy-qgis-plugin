import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Union

from qgis.core import QgsBlockingNetworkRequest, QgsNetworkAccessManager
from qgis.PyQt.QtCore import QByteArray, QEventLoop, QTextStream, QUrl
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest

from ..get_token import get_token
from . import config as api_config


def handle_blocking_reply(content: QByteArray) -> dict:
    """Handle QgsBlockingNetworkRequest reply and convert to Python dict"""
    if not content or content.isEmpty():
        return {}
    text = str(content.data(), "utf-8")
    if not text.strip():
        return {}
    return json.loads(text)


def handle_network_reply(reply: QNetworkReply) -> dict:
    """Handle QNetworkReply and convert to Python dict"""
    if reply.error() == QNetworkReply.NoError:
        status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        if status_code == 204:
            # No Content
            return {"content": {}, "error": None}
        text_stream = QTextStream(reply)
        text_stream.setCodec("UTF-8")
        text = text_stream.readAll()
        if not text.strip():
            return {"content": {}, "error": None}
        return {"content": json.loads(text), "error": None}
    else:
        error_msg = reply.errorString()
        if reply.error() in [
            QNetworkReply.ContentAccessDenied,
            QNetworkReply.AuthenticationRequiredError,
        ]:
            return {"content": None, "error": "Authentication Error"}
        elif reply.error() in [
            QNetworkReply.HostNotFoundError,
            QNetworkReply.UnknownNetworkError,
        ]:
            return {"content": None, "error": "Network Error"}
        else:
            return {"content": None, "error": f"API Error: {error_msg}"}


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
        err = blocking_request.get(req, forceRefresh=True)
        if err != QgsBlockingNetworkRequest.NoError:
            return {"content": None, "error": "Network Error"}

        reply = blocking_request.reply()
        return {"content": handle_blocking_reply(reply.content()), "error": None}

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
        if err != QgsBlockingNetworkRequest.NoError:
            return {"content": None, "error": "Network Error"}

        reply = blocking_request.reply()
        return {"content": handle_blocking_reply(reply.content()), "error": None}

    @staticmethod
    def patch(endpoint: str, data: Any) -> dict:
        """Make PATCH request to API endpoint

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

        # Use QgsNetworkAccessManager for PATCH support
        nwa_manager = QgsNetworkAccessManager.instance()
        reply = nwa_manager.sendCustomRequest(req, "PATCH".encode("utf-8"), byte_array)

        # Wait for completion synchronously
        eventLoop = QEventLoop()
        reply.finished.connect(eventLoop.quit)
        eventLoop.exec_()

        # Handle the reply
        result = handle_network_reply(reply)
        reply.deleteLater()
        return result

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
        if err != QgsBlockingNetworkRequest.NoError:
            return {"content": None, "error": "Network Error"}

        reply = blocking_request.reply()
        return {"content": handle_blocking_reply(reply.content()), "error": None}
