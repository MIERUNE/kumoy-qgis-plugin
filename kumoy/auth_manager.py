import json
import time
from typing import Optional, Tuple

from qgis.core import (
    Qgis,
    QgsBlockingNetworkRequest,
    QgsMessageLog,
    QgsNetworkReplyContent,
)
from qgis.PyQt.QtCore import (
    QByteArray,
    QCoreApplication,
    QObject,
    QTimer,
    QUrl,
    pyqtSignal,
)
from qgis.PyQt.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from ..pyqt_version import Q_NETWORK_REPLY_ERROR, Q_NETWORK_REQUEST_HEADER
from .api.error import format_api_error
from .constants import LOG_CATEGORY


DEVICE_AUTH_CLIENT_ID = "kumoy-qgis-plugin"


class AuthManager(QObject):
    """OAuth Device Authorization Flow による認証マネージャー"""

    auth_completed = pyqtSignal(bool, str)  # success, error_message

    def __init__(self, server_url: str):
        super().__init__()
        self.server_url = server_url
        self.access_token: Optional[str] = None
        self.expires_in: Optional[int] = None
        self.user_code: Optional[str] = None
        self.device_code: Optional[str] = None
        self.verification_uri: Optional[str] = None
        self.verification_uri_complete: Optional[str] = None
        self.polling_interval: int = 5
        self._expires_in_device: int = 1800
        self._poll_timer: Optional[QTimer] = None
        self._auth_start_time: Optional[float] = None
        self._network_manager: Optional[QNetworkAccessManager] = None
        self._pending_reply: Optional[QNetworkReply] = None
        self._cancelled: bool = False
        self._completed: bool = False

    def tr(self, message: str) -> str:
        return QCoreApplication.translate("AuthManager", message)

    def request_device_code(self) -> Tuple[bool, str]:
        """デバイスコードをリクエストする。

        Returns:
            (success, user_code_or_error)
        """
        url = f"{self.server_url}/api/auth/device/code"
        data = json.dumps({"client_id": DEVICE_AUTH_CLIENT_ID}).encode("utf-8")

        try:
            req = QNetworkRequest(QUrl(url))
            req.setHeader(
                Q_NETWORK_REQUEST_HEADER.ContentTypeHeader, "application/json"
            )
            req.setRawHeader(b"Origin", self.server_url.encode("utf-8"))

            blocking_request = QgsBlockingNetworkRequest()
            err = blocking_request.post(req, QByteArray(data))

            if err != QgsBlockingNetworkRequest.NoError:
                error_message = blocking_request.errorMessage()
                reply_content: QgsNetworkReplyContent = blocking_request.reply()
                status_code = reply_content.attribute(
                    QNetworkRequest.Attribute.HttpStatusCodeAttribute
                )
                body = (
                    str(reply_content.content().data(), "utf-8")
                    if reply_content.content()
                    else ""
                )
                QgsMessageLog.logMessage(
                    f"Device code request failed: status={status_code}, body={body}, error={error_message}",
                    LOG_CATEGORY,
                    Qgis.Warning,
                )
                return False, self.tr("Failed to request device code: {}").format(
                    error_message
                )

            content = blocking_request.reply().content()
            resp_data = json.loads(str(content.data(), "utf-8"))

            self.user_code = resp_data.get("user_code") or resp_data.get("userCode")
            self.device_code = resp_data.get("device_code") or resp_data.get(
                "deviceCode"
            )
            self.verification_uri = resp_data.get("verification_uri") or resp_data.get(
                "verificationUri"
            )
            self.verification_uri_complete = resp_data.get(
                "verification_uri_complete"
            ) or resp_data.get("verificationUriComplete")
            self.polling_interval = resp_data.get("interval", 5)
            self._expires_in_device = resp_data.get("expires_in") or resp_data.get(
                "expiresIn", 1800
            )

            if not self.device_code or not self.user_code:
                return False, self.tr("Server did not return device code")

            if not self.verification_uri_complete and not self.verification_uri:
                return False, self.tr("Server did not return verification URL")

            return True, self.user_code

        except Exception as e:
            return False, self.tr("Failed to request device code: {}").format(
                format_api_error(e)
            )

    def get_verification_url(self) -> str:
        """ユーザーがブラウザで開くURLを返す"""
        return self.verification_uri_complete or self.verification_uri or ""

    def start_polling(self):
        """トークン取得のためのポーリングを開始する"""
        self._auth_start_time = time.time()
        self._poll_url = f"{self.server_url}/api/auth/device/token"
        self._poll_data = json.dumps(
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": self.device_code,
                "client_id": DEVICE_AUTH_CLIENT_ID,
            }
        ).encode("utf-8")
        self._network_manager = QNetworkAccessManager(self)
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_for_token)
        self._poll_timer.start(self.polling_interval * 1000)

    def _poll_for_token(self):
        """トークンエンドポイントを非同期でポーリングする"""
        if self._completed or self._pending_reply is not None:
            return

        if time.time() - self._auth_start_time > self._expires_in_device:
            self._cleanup()
            self.auth_completed.emit(
                False, self.tr("Device code expired. Please try again.")
            )
            return

        req = QNetworkRequest(QUrl(self._poll_url))
        req.setHeader(Q_NETWORK_REQUEST_HEADER.ContentTypeHeader, "application/json")
        req.setRawHeader(b"Origin", self.server_url.encode("utf-8"))

        reply = self._network_manager.post(req, QByteArray(self._poll_data))
        self._pending_reply = reply
        reply.finished.connect(lambda r=reply: self._on_poll_reply(r))

    def _on_poll_reply(self, reply: QNetworkReply):
        """ポーリングレスポンスを処理する"""
        self._pending_reply = None

        if self._cancelled:
            reply.deleteLater()
            return

        try:
            content = reply.readAll()
            body = (
                str(content.data(), "utf-8")
                if content and not content.isEmpty()
                else ""
            )

            if not body:
                if reply.error() != Q_NETWORK_REPLY_ERROR.NoError:
                    QgsMessageLog.logMessage(
                        f"Network error during polling: {reply.errorString()}",
                        LOG_CATEGORY,
                        Qgis.Warning,
                    )
                return

            resp_data = json.loads(body)

            if reply.error() == Q_NETWORK_REPLY_ERROR.NoError:
                token = resp_data.get("access_token") or resp_data.get("accessToken")
                if token:
                    self.access_token = token
                    self.expires_in = resp_data.get("expires_in") or resp_data.get(
                        "expiresIn"
                    )
                    self._completed = True
                    self._cleanup()
                    self.auth_completed.emit(True, "")
                    return

            error = resp_data.get("error", "")
            self._handle_poll_error(error, resp_data)

        except json.JSONDecodeError:
            QgsMessageLog.logMessage(
                f"Invalid JSON in poll response: {reply.errorString()}",
                LOG_CATEGORY,
                Qgis.Warning,
            )
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error polling for token: {format_api_error(e)}",
                LOG_CATEGORY,
                Qgis.Warning,
            )
        finally:
            reply.deleteLater()

    def _handle_poll_error(self, error: str, resp_data: dict):
        if error == "authorization_pending":
            return
        elif error == "slow_down":
            self.polling_interval += 5
            if self._poll_timer:
                self._poll_timer.setInterval(self.polling_interval * 1000)
            return
        elif error == "access_denied":
            self._cleanup()
            self.auth_completed.emit(False, self.tr("Authorization was denied."))
        elif error == "expired_token":
            self._cleanup()
            self.auth_completed.emit(
                False, self.tr("Device code expired. Please try again.")
            )
        elif error:
            description = resp_data.get("error_description", error)
            self._cleanup()
            self.auth_completed.emit(
                False, self.tr("Authentication error: {}").format(description)
            )

    def _cleanup(self):
        if self._poll_timer:
            self._poll_timer.stop()
            self._poll_timer = None
        if self._pending_reply:
            self._pending_reply.abort()
            self._pending_reply = None
        self._network_manager = None

    def poll_now(self):
        """即座にポーリングを1回実行し、タイマーをリスタートする"""
        if self._poll_timer and self._poll_timer.isActive():
            self._poll_timer.stop()
            self._poll_for_token()
            if self._poll_timer:  # _poll_for_token 内で cleanup されていない場合のみ
                self._poll_timer.start(self.polling_interval * 1000)

    def cancel_auth(self):
        self._cancelled = True
        self._cleanup()

    def get_access_token(self) -> Optional[str]:
        return self.access_token

    def get_expires_in(self) -> Optional[int]:
        return self.expires_in
