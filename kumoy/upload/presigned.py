"""S3 presigned POST/PUT へのアップロード。

本体を ``QIODevice`` から逐次送信するため、数 GB 級のファイルでもメモリに全量を
載せない。これにより OOM と、Qt5 の ``QByteArray`` が ``int`` サイズ（最大約
2GB）に制限される問題の両方を回避する。

presigned POST (multipart form) と presigned PUT (raw binary) の2方式をサポートする。
QHttpMultiPart + setBodyDevice を使った POST は Qt のバージョンによって
Transfer-Encoding: chunked で送信され、MinIO/rustfs 系の S3 互換実装が
"failed to read file stream" で拒否することがある。ラスターのような大容量バイナリ
ファイルには PUT 方式を推奨する。

進捗・中断は呼び出し側のコールバックで受け取る（``QgsProcessingFeedback`` 等の
上位概念には依存しない）。総時間ではなく「無通信が続いた時間」でタイムアウト
判定するので、巨大ファイルを正常に送っている最中に誤って中断しない。
"""

from typing import Callable, Dict, Optional

from qgis.core import QgsNetworkAccessManager
from qgis.PyQt.QtCore import QBuffer, QByteArray, QEventLoop, QFile, QTimer, QUrl
from qgis.PyQt.QtNetwork import QHttpMultiPart, QHttpPart, QNetworkRequest

from ...pyqt_version import (
    Q_HTTP_MULTIPART_CONTENT_TYPE,
    Q_IODEVICE_OPEN_MODE,
    Q_NETWORK_REQUEST_ATTRIBUTE,
    Q_NETWORK_REQUEST_HEADER,
    exec_event_loop,
)

# 一定時間アップロードの進捗が動かなければ中断する（ネットワーク無通信ガード）。
_IDLE_TIMEOUT_MS = 60_000


class UploadCanceled(Exception):
    """呼び出し側のコールバックがアップロードの中断を要求した。"""


ProgressCallback = Callable[[float], None]
"""(percent: 0-100) -> None"""

IsCanceledCallback = Callable[[], bool]
"""() -> 中断すべきなら True"""


def upload_bytes_to_presigned_post(
    url: str,
    fields: Dict[str, str],
    data: bytes,
) -> None:
    """メモリ上のバイト列を presigned POST (multipart/form-data) でアップロードする。

    presigned の各フォームフィールド（S3 キーや Content-Type を含む）を先に並べ、
    本体を ``name="file"`` のパートとして最後に置く（S3 の POST ポリシーはファイル
    パートが最後である必要がある）。ファイルパートの Content-Type は署名値と一致して
    いないと S3 が 403 を返すため、fields の Content-Type を使う。
    """
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(Q_IODEVICE_OPEN_MODE.ReadOnly)

    multipart = QHttpMultiPart(Q_HTTP_MULTIPART_CONTENT_TYPE.FormDataType)
    for field_name, field_value in fields.items():
        part = QHttpPart()
        part.setHeader(
            Q_NETWORK_REQUEST_HEADER.ContentDispositionHeader,
            f'form-data; name="{field_name}"',
        )
        part.setBody(QByteArray(str(field_value).encode("utf-8")))
        multipart.append(part)

    file_part = QHttpPart()
    file_part.setHeader(
        Q_NETWORK_REQUEST_HEADER.ContentDispositionHeader,
        'form-data; name="file"; filename="upload"',
    )
    file_part.setHeader(
        Q_NETWORK_REQUEST_HEADER.ContentTypeHeader,
        fields.get("Content-Type", ""),
    )
    buffer.setParent(multipart)  # prevent GC; device must outlive the request
    file_part.setBodyDevice(buffer)
    multipart.append(file_part)

    request = QNetworkRequest(QUrl(url))
    reply = QgsNetworkAccessManager.instance().post(request, multipart)
    multipart.setParent(reply)  # prevent GC
    _await_upload(reply, None, None)


def upload_file_to_presigned_put(
    url: str,
    file_path: str,
    content_type: str,
    progress_callback: Optional[ProgressCallback] = None,
    is_canceled: Optional[IsCanceledCallback] = None,
) -> None:
    """ファイルを presigned PUT でストリーミングアップロードする。

    presigned POST (multipart form) と異なり、ファイルデータをそのまま PUT
    ボディとして送信するため、Qt バージョンに関係なく Content-Length が正しく
    設定され、MinIO/rustfs 系の実装との互換性が高い。

    Raises:
        UploadCanceled: ``is_canceled`` が True を返した場合。
        Exception: ファイルが開けない / ネットワーク・HTTP エラー時。
    """
    file = QFile(file_path)
    if not file.open(Q_IODEVICE_OPEN_MODE.ReadOnly):
        raise Exception(f"Cannot open file for upload: {file_path}")

    request = QNetworkRequest(QUrl(url))
    request.setHeader(Q_NETWORK_REQUEST_HEADER.ContentTypeHeader, content_type)

    reply = QgsNetworkAccessManager.instance().put(request, file)
    file.setParent(reply)  # prevent GC; device must outlive the request
    _await_upload(reply, progress_callback, is_canceled)


def _await_upload(
    reply,
    progress_callback: Optional[ProgressCallback],
    is_canceled: Optional[IsCanceledCallback],
) -> None:
    """送信済みの reply をブロッキングで待ち、進捗・中断・結果検証を行う。

    POST/PUT どちらの送信方法でも結果待ちのロジックは同じなので共有する。
    """
    canceled = {"value": False}

    loop = QEventLoop()
    reply.finished.connect(loop.quit)

    # アイドルタイムアウト: 進捗のたびに測り直すので、送信が進んでいる限り発火しない。
    # QTimer は reply を親にして、reply 削除後にコールバックが残らないようにする。
    idle_timer = QTimer(reply)
    idle_timer.setSingleShot(True)
    idle_timer.timeout.connect(reply.abort)
    reply.finished.connect(idle_timer.stop)

    def on_progress(sent: int, total: int) -> None:
        idle_timer.start(_IDLE_TIMEOUT_MS)
        if is_canceled is not None and is_canceled():
            canceled["value"] = True
            reply.abort()
            return
        if progress_callback is not None and total > 0:
            progress_callback(sent / total * 100.0)

    reply.uploadProgress.connect(on_progress)
    idle_timer.start(_IDLE_TIMEOUT_MS)
    exec_event_loop(loop)

    if canceled["value"]:
        reply.deleteLater()
        raise UploadCanceled()

    if not reply.isFinished():
        reply.abort()
        reply.deleteLater()
        raise Exception("Upload failed: reply did not finish")

    # HTTP 応答を受け取れたかどうかで層を分ける。reply.error() は HTTP 4xx/5xx でも
    # 非 NoError になるため、status_code の有無でネットワーク層とアプリ層を切り分ける。
    status_code = reply.attribute(Q_NETWORK_REQUEST_ATTRIBUTE.HttpStatusCodeAttribute)
    if status_code is None:
        network_error = reply.error()
        error_string = reply.errorString()
        reply.deleteLater()
        raise Exception(
            f"Upload failed (network error {int(network_error)}): {error_string}"
        )
    if status_code not in (200, 201, 204):
        error_body = bytes(reply.readAll().data()).decode("utf-8", errors="replace")
        reply.deleteLater()
        raise Exception(f"Upload failed (HTTP {status_code}): {error_body}")

    reply.deleteLater()
