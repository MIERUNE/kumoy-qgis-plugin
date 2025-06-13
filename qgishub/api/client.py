import json
from typing import Any, Dict, Optional

from PyQt5.QtCore import QByteArray, QUrl
from PyQt5.QtNetwork import QNetworkRequest
from qgis.core import QgsBlockingNetworkRequest

from ..config import config as qgishub_config
from ..get_token import get_token


class ApiClient:
    """API client for STRATO backend using QgsBlockingNetworkRequest"""

    @staticmethod
    def handle_reply(reply_content: QByteArray, reply_error: str) -> dict:
        """Handle network reply and convert to Python dict"""
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
    def get(endpoint: str, params: Optional[Dict] = None) -> dict:
        """Make blocking GET request to API endpoint"""
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

        # Execute blocking request
        blocking_request = QgsBlockingNetworkRequest()
        err = blocking_request.get(req)

        if err != QgsBlockingNetworkRequest.NoError:
            error_msg = blocking_request.errorMessage()
            return ApiClient.handle_reply(QByteArray(), error_msg)

        reply = blocking_request.reply()
        return ApiClient.handle_reply(reply.content(), "")

    @staticmethod
    def post(endpoint: str, data: Any) -> dict:
        """Make blocking POST request to API endpoint"""
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

        # Use json.dumps to preserve dictionary order
        json_data = json.dumps(data, ensure_ascii=False)
        byte_array = QByteArray(json_data.encode("utf-8"))

        # Execute blocking request
        blocking_request = QgsBlockingNetworkRequest()
        err = blocking_request.post(req, byte_array)

        if err != QgsBlockingNetworkRequest.NoError:
            error_msg = blocking_request.errorMessage()
            return ApiClient.handle_reply(QByteArray(), error_msg)

        reply = blocking_request.reply()
        return ApiClient.handle_reply(reply.content(), "")

    @staticmethod
    def patch(endpoint: str, data: Any) -> dict:
        """Make blocking PATCH request to API endpoint"""
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

        # Use json.dumps to preserve dictionary order
        json_data = json.dumps(data, ensure_ascii=False)
        byte_array = QByteArray(json_data.encode("utf-8"))

        # Execute blocking request
        blocking_request = QgsBlockingNetworkRequest()
        # Note: QgsBlockingNetworkRequest doesn't have direct PATCH support,
        # so we need to use the lower-level approach
        err = blocking_request.post(req, byte_array, forceRefresh=True)

        if err != QgsBlockingNetworkRequest.NoError:
            error_msg = blocking_request.errorMessage()
            return ApiClient.handle_reply(QByteArray(), error_msg)

        reply = blocking_request.reply()
        return ApiClient.handle_reply(reply.content(), "")

    @staticmethod
    def delete(endpoint: str) -> dict:
        """Make blocking DELETE request to API endpoint"""
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

        # Execute blocking request
        blocking_request = QgsBlockingNetworkRequest()
        err = blocking_request.deleteResource(req)

        if err != QgsBlockingNetworkRequest.NoError:
            error_msg = blocking_request.errorMessage()
            return ApiClient.handle_reply(QByteArray(), error_msg)

        reply = blocking_request.reply()
        return ApiClient.handle_reply(reply.content(), "")
