import json
import time
import urllib.error
import urllib.request
from typing import Optional, Tuple

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal

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

    def request_device_code(self) -> Tuple[bool, str]:
        """デバイスコードをリクエストする。

        Returns:
            (success, user_code_or_error)
        """
        url = f"{self.server_url}/api/auth/device/code"
        data = json.dumps({"client_id": DEVICE_AUTH_CLIENT_ID}).encode("utf-8")
        headers = {"Content-Type": "application/json"}

        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req) as response:
                resp_data = json.loads(response.read().decode("utf-8"))

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
                return False, "Server did not return device code"

            return True, self.user_code

        except Exception as e:
            return False, f"Failed to request device code: {format_api_error(e)}"

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
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll_for_token)
        self._poll_timer.start(self.polling_interval * 1000)

    def _poll_for_token(self):
        """トークンエンドポイントをポーリングする"""
        if time.time() - self._auth_start_time > self._expires_in_device:
            self._cleanup()
            self.auth_completed.emit(False, "Device code expired. Please try again.")
            return

        try:
            req = urllib.request.Request(
                self._poll_url,
                data=self._poll_data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req) as response:
                resp_data = json.loads(response.read().decode("utf-8"))

            token = resp_data.get("access_token") or resp_data.get("accessToken")
            if token:
                self.access_token = token
                self.expires_in = resp_data.get("expires_in") or resp_data.get(
                    "expiresIn"
                )
                self._cleanup()
                self.auth_completed.emit(True, "")
                return

            error = resp_data.get("error", "")
            self._handle_poll_error(error, resp_data)

        except urllib.error.HTTPError as e:
            try:
                error_body = e.read().decode("utf-8")
                error_data = json.loads(error_body)
                error = error_data.get("error", "")
                self._handle_poll_error(error, error_data)
            except Exception as parse_err:
                QgsMessageLog.logMessage(
                    f"Error parsing poll response: {format_api_error(parse_err)}",
                    LOG_CATEGORY,
                    Qgis.Warning,
                )
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error polling for token: {format_api_error(e)}",
                LOG_CATEGORY,
                Qgis.Warning,
            )

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
            self.auth_completed.emit(False, "Authorization was denied.")
        elif error == "expired_token":
            self._cleanup()
            self.auth_completed.emit(False, "Device code expired. Please try again.")
        elif error:
            description = resp_data.get("error_description", error)
            self._cleanup()
            self.auth_completed.emit(False, f"Authentication error: {description}")

    def _cleanup(self):
        if self._poll_timer:
            self._poll_timer.stop()
            self._poll_timer = None

    def cancel_auth(self):
        self._cleanup()

    def get_access_token(self) -> Optional[str]:
        return self.access_token

    def get_expires_in(self) -> Optional[int]:
        return self.expires_in
