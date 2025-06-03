import json
from typing import Any, Dict, Optional

from PyQt5.QtCore import QByteArray, QEventLoop, QJsonDocument, QTextStream, QUrl
from PyQt5.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.core import QgsNetworkAccessManager

from ..config import config as qgishub_config
from ..get_token import get_token


class ApiClient:
    """Base API client for STRATO backend"""

    @staticmethod
    def handle_reply(reply: QNetworkReply) -> dict:
        """Handle network reply and convert to Python dict"""
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
            print(f"API Error: {reply.error()}")
            print(f"Error message: {reply.errorString()}")
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
                raise Exception(reply.errorString())

    @staticmethod
    def get(endpoint: str, params: Optional[Dict] = None) -> dict:
        """Make GET request to API endpoint"""
        nwa_manager = QgsNetworkAccessManager.instance()

        # Build URL with query parameters if provided
        url = f"{qgishub_config.API_URL}{endpoint}"
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
        eventLoop = QEventLoop()
        reply = nwa_manager.get(req)
        reply.finished.connect(eventLoop.quit)
        eventLoop.exec_()

        return ApiClient.handle_reply(reply)

    @staticmethod
    def post(endpoint: str, data: Any) -> dict:
        """Make POST request to API endpoint"""
        nwa_manager = QgsNetworkAccessManager.instance()
        url = f"{qgishub_config.API_URL}{endpoint}"

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

        # Execute request
        eventLoop = QEventLoop()
        
        # Use json.dumps to preserve dictionary order instead of QJsonDocument
        # which might reorder keys alphabetically
        json_data = json.dumps(data, ensure_ascii=False)
        byte_array = QByteArray(json_data.encode('utf-8'))
        
        reply = nwa_manager.post(req, byte_array)
        reply.finished.connect(eventLoop.quit)
        eventLoop.exec_()

        return ApiClient.handle_reply(reply)

    @staticmethod
    def patch(endpoint: str, data: Any) -> dict:
        """Make PATCH request to API endpoint"""
        nwa_manager = QgsNetworkAccessManager.instance()
        url = f"{qgishub_config.API_URL}{endpoint}"

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

        # Execute request
        eventLoop = QEventLoop()
        
        # Use json.dumps to preserve dictionary order
        json_data = json.dumps(data, ensure_ascii=False)
        byte_array = QByteArray(json_data.encode('utf-8'))
        
        reply = nwa_manager.sendCustomRequest(
            req, "PATCH".encode("utf-8"), byte_array
        )
        reply.finished.connect(eventLoop.quit)
        eventLoop.exec_()

        return ApiClient.handle_reply(reply)

    @staticmethod
    def delete(endpoint: str) -> dict:
        """Make DELETE request to API endpoint"""
        nwa_manager = QgsNetworkAccessManager.instance()
        url = f"{qgishub_config.API_URL}{endpoint}"

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
        eventLoop = QEventLoop()
        reply = nwa_manager.deleteResource(req)
        reply.finished.connect(eventLoop.quit)
        eventLoop.exec_()

        return ApiClient.handle_reply(reply)
