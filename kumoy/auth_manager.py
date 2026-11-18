"""OAuth device authorization flow (RFC 8628) against better-auth.

Every request runs in a QgsTask so the login dialog stays responsive. Signals
fire on the main thread.
"""

import time
from typing import Optional

from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal

from .. import i18n
from .api import auth
from .api.error import AppError, NetworkError, format_api_error
from .tasks import run_task


class DeviceLogin(QObject):
    # user_code, verification_url: show them and open the browser
    code_received = pyqtSignal(str, str)
    # auth.Tokens on success
    succeeded = pyqtSignal(object)
    # translated message; the flow is over
    failed = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._code: Optional[auth.DeviceCode] = None
        self._deadline = 0.0
        self._interval_ms = 5000
        self._active = False
        self._polling = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._poll)

    def start(self) -> None:
        self.cancel()
        self._active = True
        run_task(
            i18n.tr("Kumoy login"),
            lambda task: auth.request_device_code(),
            self._on_code,
            self._on_code_error,
        )

    def cancel(self) -> None:
        self._active = False
        self._timer.stop()

    def poll_now(self) -> None:
        """Poll immediately, e.g. when the user says they approved in the browser."""
        if self._active and self._code is not None and not self._polling:
            self._timer.stop()
            self._poll()

    def _on_code(self, code: auth.DeviceCode) -> None:
        if not self._active:
            return
        self._code = code
        self._deadline = time.monotonic() + code.expires_in
        self._interval_ms = max(code.interval, 1) * 1000
        self.code_received.emit(code.user_code, code.verification_url)
        self._timer.start(self._interval_ms)

    def _on_code_error(self, e: Exception) -> None:
        if self._active:
            self._fail(i18n.tr("Failed to start login: {}").format(format_api_error(e)))

    def _poll(self) -> None:
        if not self._active or self._code is None:
            return
        if time.monotonic() > self._deadline:
            self._fail(i18n.tr("The login code expired. Please try again."))
            return
        self._polling = True
        device_code = self._code.device_code
        run_task(
            i18n.tr("Kumoy login"),
            lambda task: auth.poll_device_token(device_code),
            self._on_poll_result,
            self._on_poll_error,
        )

    def _on_poll_result(self, tokens: Optional[auth.Tokens]) -> None:
        self._polling = False
        if not self._active:
            return
        if tokens:
            self._active = False
            self.succeeded.emit(tokens)
        else:
            self._timer.start(self._interval_ms)

    def _on_poll_error(self, e: Exception) -> None:
        self._polling = False
        if not self._active:
            return
        code = e.error if isinstance(e, AppError) else ""
        if code == "slow_down":
            self._interval_ms += 5000
        elif isinstance(e, NetworkError):
            pass  # transient: keep polling until the code expires
        elif code == "access_denied":
            self._fail(i18n.tr("Login was denied in the browser."))
            return
        elif code == "expired_token":
            self._fail(i18n.tr("The login code expired. Please try again."))
            return
        else:
            self._fail(i18n.tr("Login failed: {}").format(format_api_error(e)))
            return
        self._timer.start(self._interval_ms)

    def _fail(self, message: str) -> None:
        self.cancel()
        self.failed.emit(message)
