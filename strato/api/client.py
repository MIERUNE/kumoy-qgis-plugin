import json
from typing import Any, Dict, Optional

from qgis.core import QgsBlockingNetworkRequest, QgsNetworkAccessManager
from qgis.PyQt.QtCore import QByteArray, QEventLoop, QTextStream, QUrl
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest

from ..get_token import get_token
from . import config as api_config


class ApiClient:
    """Base API client for STRATO backend"""

    @staticmethod
    def handle_blocking_reply(reply_content: QByteArray, reply_error: str) -> dict:
        """Handle QgsBlockingNetworkRequest reply and convert to Python dict"""
        if not reply_error:
            if not reply_content or reply_content.isEmpty():
                return {}
            text = str(reply_content.data(), "utf-8")
            if not text.strip():
                return {}
            return json.loads(text)
        else:
            if "401" in reply_error or "403" in reply_error:
                raise Exception("Authentication Error")
            elif "Network" in reply_error:
                raise Exception("Network Error")
            else:
                raise Exception(f"API Error: {reply_error}")

    @staticmethod
    def handle_network_reply(reply: QNetworkReply) -> dict:
        """Handle QNetworkReply and convert to Python dict"""
        if reply.error() == QNetworkReply.NoError:
            status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            if status_code == 204:
                # No Content
                return {}
            text_stream = QTextStream(reply)
            text_stream.setCodec("UTF-8")
            text = text_stream.readAll()
            if not text.strip():
                return {}
            return json.loads(text)
        else:
            error_msg = reply.errorString()
            if reply.error() in [
                QNetworkReply.ContentAccessDenied,
                QNetworkReply.AuthenticationRequiredError,
            ]:
                raise Exception("Authentication Error")
            elif reply.error() in [
                QNetworkReply.HostNotFoundError,
                QNetworkReply.UnknownNetworkError,
            ]:
                raise Exception("Network Error")
            else:
                raise Exception(f"API Error: {error_msg}")

    @staticmethod
    def get(endpoint: str, params: Optional[Dict] = None) -> dict:
        """Make GET request to API endpoint"""
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
            raise Exception("Authentication Error")

        req.setRawHeader(
            "Authorization".encode("utf-8"),
            f"Bearer {token}".encode("utf-8"),
        )

        # Execute request
        blocking_request = QgsBlockingNetworkRequest()
        blocking_request.get(req, forceRefresh=True)
        reply = blocking_request.reply()
        return ApiClient.handle_blocking_reply(reply.content(), "")

    @staticmethod
    def post(endpoint: str, data: Any) -> dict:
        """Make POST request to API endpoint"""
        _api_config = api_config.get_api_config()
        url = f"{_api_config.API_URL}{endpoint}"

        # Create request with authorization header
        req = QNetworkRequest(QUrl(url))
        token = get_token()

        if not token:
            raise Exception("Authentication Error")

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
        blocking_request.post(req, byte_array)
        reply = blocking_request.reply()
        return ApiClient.handle_blocking_reply(reply.content(), "")

    @staticmethod
    def patch(endpoint: str, data: Any) -> dict:
        """Make PATCH request to API endpoint"""
        _api_config = api_config.get_api_config()
        url = f"{_api_config.API_URL}{endpoint}"

        # Create request with authorization header
        req = QNetworkRequest(QUrl(url))
        token = get_token()

        if not token:
            raise Exception("Authentication Error")

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
        result = ApiClient.handle_network_reply(reply)
        reply.deleteLater()
        return result

    @staticmethod
    def delete(endpoint: str) -> dict:
        """Make DELETE request to API endpoint"""
        _api_config = api_config.get_api_config()
        url = f"{_api_config.API_URL}{endpoint}"

        # Create request with authorization header
        req = QNetworkRequest(QUrl(url))
        token = get_token()

        if not token:
            raise Exception("Authentication Error")

        req.setRawHeader(
            "Authorization".encode("utf-8"),
            f"Bearer {token}".encode("utf-8"),
        )

        # Execute request
        blocking_request = QgsBlockingNetworkRequest()
        blocking_request.deleteResource(req)
        reply = blocking_request.reply()
        return ApiClient.handle_blocking_reply(reply.content(), "")
