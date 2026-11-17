"""Uploads to S3 presigned URLs.

- PUT streams a file (raster COGs, up to 4 GB) from disk. A raw PUT body gets
  a real Content-Length on every Qt version; a large multipart POST may go out
  chunked, which MinIO/rustfs reject ("failed to read file stream").
- POST (multipart form) sends small in-memory assets (sprites).

Also home of the reply-waiting helpers kumoy/download.py shares; this module
stays free of cache/API imports so sprite uploads can use it without cycles.
"""

import uuid
from typing import Callable, Dict, Optional

from qgis.core import QgsBlockingNetworkRequest, QgsNetworkAccessManager
from qgis.PyQt.QtCore import QByteArray, QEventLoop, QFile, QTimer, QUrl
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest

from ...pyqt_version import (
    Q_IODEVICE_OPEN_MODE,
    Q_NETWORK_REPLY_ERROR,
    Q_NETWORK_REQUEST_ATTRIBUTE,
    Q_NETWORK_REQUEST_HEADER,
    exec_event_loop,
)
from ..api.error import AppError, NetworkError
from ..tasks import Canceled

ProgressCallback = Callable[[float], None]  # percent 0-100
IsCanceledCallback = Callable[[], bool]

# Abort when a transfer makes no progress for this long
_IDLE_TIMEOUT_MS = 60_000
# After the last byte, S3 verifies and stores the object before answering;
# for gigabytes that takes minutes, with no progress events meanwhile
_RESPONSE_TIMEOUT_MS = 600_000
_CANCEL_POLL_MS = 200


def _neutralize_qgis_network_timeout(reply: QNetworkReply) -> None:
    """Disable QgsNetworkAccessManager's own idle timeout on `reply`.

    QGIS attaches a QTimer named "timeoutTimer" (default 60 s) that aborts a
    reply without progress events. After the last byte of an upload, S3 may
    take minutes to answer, with no progress at all, so QGIS would abort a
    successful upload. The timer is restarted on every progress event, so
    stopping it is not enough: disconnect it. wait_for_reply() takes over.
    """
    timer = reply.findChild(QTimer, "timeoutTimer")
    if timer is None:
        return  # timeout disabled in the settings, or QGIS internals changed
    timer.stop()
    try:
        timer.timeout.disconnect()
    except TypeError:
        pass


def wait_for_reply(
    reply: QNetworkReply,
    progress_signal,
    progress_callback: Optional[ProgressCallback] = None,
    is_canceled: Optional[IsCanceledCallback] = None,
    response_timeout_ms: int = _IDLE_TIMEOUT_MS,
) -> bool:
    """Block (worker thread) until `reply` finishes. True when canceled.

    `progress_signal` is the reply's uploadProgress or downloadProgress. Once
    every byte is sent, the server's answer may take `response_timeout_ms`.
    """
    _neutralize_qgis_network_timeout(reply)
    loop = QEventLoop()
    reply.finished.connect(loop.quit)

    idle = QTimer()
    idle.setSingleShot(True)
    idle.timeout.connect(reply.abort)

    canceled = []

    def on_progress(done: int, total: int) -> None:
        if done <= 0 and total <= 0:
            return  # Qt reports (0, 0) on abort
        idle.start(response_timeout_ms if 0 < total <= done else _IDLE_TIMEOUT_MS)
        if progress_callback is not None and total > 0:
            progress_callback(done * 100.0 / total)

    def poll_canceled() -> None:
        # A timer rather than progress events: none arrive while S3 answers
        if is_canceled is not None and is_canceled():
            canceled.append(True)
            reply.abort()

    poller = QTimer()
    poller.timeout.connect(poll_canceled)
    poller.start(_CANCEL_POLL_MS)
    progress_signal.connect(on_progress)
    idle.start(_IDLE_TIMEOUT_MS)
    poll_canceled()
    if not reply.isFinished():
        exec_event_loop(loop)
    idle.stop()
    poller.stop()
    return bool(canceled)


def raise_for_status(reply: QNetworkReply, what: str) -> None:
    status = reply.attribute(Q_NETWORK_REQUEST_ATTRIBUTE.HttpStatusCodeAttribute)
    if status is not None and not 200 <= int(status) < 300:
        raise AppError(f"{what} failed (HTTP {status})", status=int(status))
    # A connection lost mid-body keeps its 200 status: check the error too, or
    # a truncated download would pass
    if status is None or reply.error() != Q_NETWORK_REPLY_ERROR.NoError:
        raise NetworkError(f"{what} failed", reply.errorString())


class UploadCanceled(Canceled):
    """The `is_canceled` callback asked to stop."""


def upload_bytes_to_presigned_post(
    url: str, fields: Dict[str, str], data: bytes
) -> None:
    """POST `data` with the presigned form `fields`. Blocks; any thread.

    S3 requires the file part last, and its Content-Type must equal the signed
    one, so it is taken from `fields`.
    """
    boundary = uuid.uuid4().hex
    body = b""
    for name, value in fields.items():
        body += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
            f"\r\n\r\n{value}\r\n"
        ).encode("utf-8")
    file_header = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        'filename="upload"\r\n'
    )
    if fields.get("Content-Type"):
        file_header += f"Content-Type: {fields['Content-Type']}\r\n"
    body += (file_header + "\r\n").encode("utf-8") + data
    body += f"\r\n--{boundary}--\r\n".encode("utf-8")

    request = QNetworkRequest(QUrl(url))
    request.setHeader(
        Q_NETWORK_REQUEST_HEADER.ContentTypeHeader,
        f"multipart/form-data; boundary={boundary}",
    )
    blocking = QgsBlockingNetworkRequest()
    if blocking.post(request, QByteArray(body)) != QgsBlockingNetworkRequest.NoError:
        reply = blocking.reply()
        raise AppError(
            "Upload failed",
            bytes(reply.content().data()).decode("utf-8", "replace")
            or blocking.errorMessage(),
        )


def upload_file_to_presigned_put(
    url: str,
    file_path: str,
    content_type: str,
    progress_callback: Optional[ProgressCallback] = None,
    is_canceled: Optional[IsCanceledCallback] = None,
) -> None:
    """Stream `file_path` to a presigned PUT URL. Worker thread only.

    `progress_callback` reaches 100 when every byte is on the wire; the upload
    is complete only when this returns. Raises UploadCanceled on cancel.
    """
    file = QFile(file_path)
    if not file.open(Q_IODEVICE_OPEN_MODE.ReadOnly):
        raise OSError(f"Cannot read {file_path}: {file.errorString()}")

    request = QNetworkRequest(QUrl(url))
    request.setHeader(Q_NETWORK_REQUEST_HEADER.ContentTypeHeader, content_type)
    reply = QgsNetworkAccessManager.instance().put(request, file)
    file.setParent(reply)  # the device must outlive the request
    try:
        if wait_for_reply(
            reply,
            reply.uploadProgress,
            progress_callback,
            is_canceled,
            _RESPONSE_TIMEOUT_MS,
        ):
            raise UploadCanceled()
        try:
            raise_for_status(reply, "Upload")
        except AppError as e:
            # S3 explains itself in the body (expired signature, size mismatch)
            body = bytes(reply.readAll().data()).decode("utf-8", "replace")
            if body:
                e.error = body
            raise
    finally:
        reply.deleteLater()
