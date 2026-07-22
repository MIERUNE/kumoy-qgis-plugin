"""S3 presigned POST/PUT へのアップロード。

- PUT (raw binary): ラスタ COG 用。ファイルを ``QIODevice`` から逐次送信する
  ため、数 GB 級でもメモリに全量を載せない。これにより OOM と、Qt5 の
  ``QByteArray`` が ``int`` サイズ（最大約 2GB）に制限される問題の両方を回避する。
- POST (multipart form): スプライト等、メモリ上の小さなアセット用。大容量
  ファイルを QHttpMultiPart + setBodyDevice で POST すると Qt のバージョンに
  よって Transfer-Encoding: chunked で送信され、MinIO/rustfs 系の S3 互換実装が
  "failed to read file stream" で拒否することがあるため、大容量バイナリには
  PUT を使う。

進捗・中断は呼び出し側のコールバックで受け取る（``QgsProcessingFeedback`` 等の
上位概念には依存しない）。総時間ではなく「無通信が続いた時間」でタイムアウト
判定するので、巨大ファイルを正常に送っている最中に誤って中断しない。

なお進捗 100%（全バイトをソケットへ書き終えた時点）はアップロード完了ではない。
S3 互換サーバはオブジェクトの書き込み・検証を終えるまで応答を返さないため、
その後に「応答待ち」フェーズが残る。応答待ちは進捗イベントが一切来ないので、
送信中の無通信ガードとは別の（十分長い）タイムアウトを適用する。

QgsNetworkAccessManager 自身も無通信タイムアウト（デフォルト60秒）で reply を
abort するため、そのままでは応答待ちフェーズが 60 秒を超えると QGIS 側に
中断されてしまう。ガードは本モジュールの二段タイムアウトに一本化し、QGIS 側の
タイマーは reply ごとに無効化する（``_neutralize_qgis_network_timeout``）。
"""

from typing import Callable, Dict, Optional

from qgis.core import QgsNetworkAccessManager
from qgis.PyQt.QtCore import QBuffer, QByteArray, QEventLoop, QFile, QTimer, QUrl
from qgis.PyQt.QtNetwork import (
    QHttpMultiPart,
    QHttpPart,
    QNetworkReply,
    QNetworkRequest,
)

from ...pyqt_version import (
    Q_HTTP_MULTIPART_CONTENT_TYPE,
    Q_IODEVICE_OPEN_MODE,
    Q_NETWORK_REQUEST_ATTRIBUTE,
    Q_NETWORK_REQUEST_HEADER,
    exec_event_loop,
)

# 一定時間アップロードの進捗が動かなければ中断する（ネットワーク無通信ガード）。
_IDLE_TIMEOUT_MS = 60_000

# 全バイト送信後、サーバの HTTP 応答を待つ上限。数 GB 級オブジェクトの書き込み・
# 検証には分単位かかり得るため、送信中の無通信ガードよりずっと長くとる。
_RESPONSE_TIMEOUT_MS = 600_000

# 応答待ち中も Cancel を効かせるための is_canceled ポーリング間隔。
_CANCEL_POLL_INTERVAL_MS = 500


class UploadCanceled(Exception):
    """呼び出し側のコールバックがアップロードの中断を要求した。"""


ProgressCallback = Callable[[float], None]
"""(percent: 0-100) -> None

percent は「ソケットへ書き終えたバイト数」の割合。100 でもサーバ応答待ちが
残っており、アップロード完了は関数のリターンで判断すること。
"""

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
    # Content-Type は署名対象なので fields にある場合のみ付与する。空値で
    # ヘッダを立てると S3 互換実装のポリシー検証を壊しうるため、無ければ省略。
    content_type = fields.get("Content-Type")
    if content_type:
        file_part.setHeader(
            Q_NETWORK_REQUEST_HEADER.ContentTypeHeader,
            content_type,
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


def _neutralize_qgis_network_timeout(reply: QNetworkReply) -> None:
    """QGIS (QgsNetworkAccessManager) 側の無通信タイムアウトを無効化する。

    QGIS は reply 生成時に objectName "timeoutTimer" の QTimer を子として付け、
    無通信が続くと reply を abort する。このタイマーは進捗イベントのたびに
    ``timer.start()`` で再始動されるため stop だけでは足りず、timeout シグナルを
    切断して発火しても何も起きないようにする。タイマーが見つからない場合
    （ユーザー設定でタイムアウト無効、または将来の QGIS 内部変更）は何もしない。
    """
    timer = reply.findChild(QTimer, "timeoutTimer")
    if timer is None:
        return
    timer.stop()
    try:
        timer.timeout.disconnect()
    except TypeError:
        # timeout が未接続（または既に切断済み）でも、無効化は best-effort で継続する。
        pass


def _await_upload(
    reply: QNetworkReply,
    progress_callback: Optional[ProgressCallback],
    is_canceled: Optional[IsCanceledCallback],
) -> None:
    """送信済みの reply をブロッキングで待ち、進捗・中断・結果検証を行う。

    POST/PUT どちらの送信方法でも結果待ちのロジックは同じなので共有する。
    """
    _neutralize_qgis_network_timeout(reply)

    canceled = {"value": False}

    loop = QEventLoop()
    reply.finished.connect(loop.quit)

    # タイムアウト: 進捗のたびに測り直すので、送信が進んでいる限り発火しない。
    # 全バイト送信後はサーバ応答待ちに入り進捗イベントが来なくなるため、
    # そこからは応答待ち用の長いタイムアウトに切り替える。
    # QTimer は reply を親にして、reply 削除後にコールバックが残らないようにする。
    idle_timer = QTimer(reply)
    idle_timer.setSingleShot(True)
    idle_timer.timeout.connect(reply.abort)
    reply.finished.connect(idle_timer.stop)

    def on_progress(sent: int, total: int) -> None:
        # Qt は中断時などに (0, 0) を発火することがあるので活動とみなさない。
        if total <= 0:
            return
        if sent >= total:
            idle_timer.start(_RESPONSE_TIMEOUT_MS)
        else:
            idle_timer.start(_IDLE_TIMEOUT_MS)
        if progress_callback is not None:
            progress_callback(sent / total * 100.0)

    # Cancel は進捗イベント経由だと応答待ち中に検知できないため、
    # 独立した周期タイマーでポーリングする。
    if is_canceled is not None:
        cancel_timer = QTimer(reply)
        reply.finished.connect(cancel_timer.stop)

        def poll_canceled() -> None:
            if is_canceled():
                canceled["value"] = True
                reply.abort()

        cancel_timer.timeout.connect(poll_canceled)
        cancel_timer.start(_CANCEL_POLL_INTERVAL_MS)

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
