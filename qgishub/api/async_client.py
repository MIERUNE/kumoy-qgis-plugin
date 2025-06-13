import json
from typing import Any, Callable, Dict, Optional

from PyQt5.QtCore import QByteArray, QObject, QUrl, pyqtSignal
from PyQt5.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.core import QgsNetworkAccessManager

from ..config import config as qgishub_config
from ..get_token import get_token


class AsyncApiClient(QObject):
    """Asynchronous API client for STRATO backend that doesn't block the main thread"""

    # Signal emitted when a request completes successfully
    requestFinished = pyqtSignal(dict)
    # Signal emitted when a request fails
    requestFailed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._replies = []  # Keep track of active replies to prevent GC

    def _handle_reply(self, reply: QNetworkReply, callback: Optional[Callable] = None):
        """Handle network reply and convert to Python dict"""
        try:
            if reply.error() == QNetworkReply.NoError:
                status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
                if status_code == 204:
                    # No Content
                    result = {}
                else:
                    reply_data = reply.readAll()
                    text = str(reply_data.data(), 'utf-8')
                    if not text.strip():
                        result = {}
                    else:
                        result = json.loads(text)
                
                if callback:
                    callback(result)
                self.requestFinished.emit(result)
            else:
                error_msg = f"API Error: {reply.error()} - {reply.errorString()}"
                if reply.error() in [
                    QNetworkReply.ContentAccessDenied,
                    QNetworkReply.AuthenticationRequiredError,
                ]:
                    error_msg = "Authentication Error"
                elif reply.error() in [
                    QNetworkReply.HostNotFoundError,
                    QNetworkReply.UnknownNetworkError,
                ]:
                    error_msg = "Network Error"
                
                if callback:
                    callback(None, error_msg)
                self.requestFailed.emit(error_msg)
        finally:
            # Clean up
            reply.deleteLater()
            if reply in self._replies:
                self._replies.remove(reply)

    def get(self, endpoint: str, params: Optional[Dict] = None, callback: Optional[Callable] = None):
        """Make asynchronous GET request to API endpoint"""
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
            if callback:
                callback(None, "Authentication Error")
            self.requestFailed.emit("Authentication Error")
            return

        req.setRawHeader(
            "Authorization".encode("utf-8"),
            f"Bearer {token}".encode("utf-8"),
        )

        # Execute request asynchronously
        reply = nwa_manager.get(req)
        self._replies.append(reply)
        reply.finished.connect(lambda: self._handle_reply(reply, callback))

    def post(self, endpoint: str, data: Any, callback: Optional[Callable] = None):
        """Make asynchronous POST request to API endpoint"""
        nwa_manager = QgsNetworkAccessManager.instance()
        url = f"{qgishub_config.API_URL}{endpoint}"

        # Create request with authorization header
        req = QNetworkRequest(QUrl(url))
        token = get_token()

        if not token:
            if callback:
                callback(None, "Authentication Error")
            self.requestFailed.emit("Authentication Error")
            return

        req.setRawHeader(
            "Authorization".encode("utf-8"),
            f"Bearer {token}".encode("utf-8"),
        )
        req.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")

        # Use json.dumps to preserve dictionary order
        json_data = json.dumps(data, ensure_ascii=False)
        byte_array = QByteArray(json_data.encode("utf-8"))

        # Execute request asynchronously
        reply = nwa_manager.post(req, byte_array)
        self._replies.append(reply)
        reply.finished.connect(lambda: self._handle_reply(reply, callback))

    def patch(self, endpoint: str, data: Any, callback: Optional[Callable] = None):
        """Make asynchronous PATCH request to API endpoint"""
        nwa_manager = QgsNetworkAccessManager.instance()
        url = f"{qgishub_config.API_URL}{endpoint}"

        # Create request with authorization header
        req = QNetworkRequest(QUrl(url))
        token = get_token()

        if not token:
            if callback:
                callback(None, "Authentication Error")
            self.requestFailed.emit("Authentication Error")
            return

        req.setRawHeader(
            "Authorization".encode("utf-8"),
            f"Bearer {token}".encode("utf-8"),
        )
        req.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")

        # Use json.dumps to preserve dictionary order
        json_data = json.dumps(data, ensure_ascii=False)
        byte_array = QByteArray(json_data.encode("utf-8"))

        # Execute request asynchronously
        reply = nwa_manager.sendCustomRequest(req, "PATCH".encode("utf-8"), byte_array)
        self._replies.append(reply)
        reply.finished.connect(lambda: self._handle_reply(reply, callback))

    def delete(self, endpoint: str, callback: Optional[Callable] = None):
        """Make asynchronous DELETE request to API endpoint"""
        nwa_manager = QgsNetworkAccessManager.instance()
        url = f"{qgishub_config.API_URL}{endpoint}"

        # Create request with authorization header
        req = QNetworkRequest(QUrl(url))
        token = get_token()

        if not token:
            if callback:
                callback(None, "Authentication Error")
            self.requestFailed.emit("Authentication Error")
            return

        req.setRawHeader(
            "Authorization".encode("utf-8"),
            f"Bearer {token}".encode("utf-8"),
        )

        # Execute request asynchronously
        reply = nwa_manager.deleteResource(req)
        self._replies.append(reply)
        reply.finished.connect(lambda: self._handle_reply(reply, callback))