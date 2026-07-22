"""HTTP GET を直接ファイルへストリーミング保存する。

presigned GET URL から数 GB 級の COG を取得するため、reply の本体を
``readyRead`` のたびに ``QFile`` へ書き出し、メモリに全量を載せない。これにより
OOM と、Qt5 の ``QByteArray`` が ``int`` サイズ（最大約 2GB）に制限される問題の
両方を回避する（アップロード側の ``upload/presigned.py`` と対の関係）。

進捗・中断は呼び出し側のコールバックで受け取り、``QgsProcessingFeedback`` 等の
上位概念には依存しない。総時間ではなく「無通信が続いた時間」でタイムアウト判定する
ので、巨大ファイルを正常に受信している最中に誤って中断しない。

メインスレッドでローカルイベントループを回して待つ。``QgsNetworkAccessManager`` の
シグナル駆動を使うため、ワーカースレッドからは呼ばないこと。
"""

from typing import Callable, Optional

from qgis.core import QgsNetworkAccessManager
from qgis.PyQt.QtCore import QEventLoop, QFile, QTimer, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest

from ..pyqt_version import (
    Q_IODEVICE_OPEN_MODE,
    Q_NETWORK_REQUEST_ATTRIBUTE,
    exec_event_loop,
)

# 一定時間ダウンロードの進捗が動かなければ中断する（ネットワーク無通信ガード）。
_IDLE_TIMEOUT_MS = 60_000

ProgressCallback = Callable[[float], None]
"""(percent: 0-100) -> None"""

IsCanceledCallback = Callable[[], bool]
"""() -> 中断すべきなら True"""


class DownloadCanceled(Exception):
    """呼び出し側のコールバックがダウンロードの中断を要求した。"""


def download_to_file(
    url: str,
    dest_path: str,
    progress_callback: Optional[ProgressCallback] = None,
    is_canceled: Optional[IsCanceledCallback] = None,
) -> None:
    """``url`` の内容を ``dest_path`` へストリーミング保存する。

    中断・失敗時は書きかけのファイルを残さない（呼び出し側に「完全なファイルが
    在るか、何も無いか」だけを見せる）。

    Raises:
        DownloadCanceled: ``is_canceled`` が True を返した場合。
        Exception: ファイルが開けない / ネットワーク・HTTP エラー時。
    """
    out = QFile(dest_path)
    if not out.open(Q_IODEVICE_OPEN_MODE.WriteOnly):
        raise Exception(f"Cannot open file for download: {dest_path}")

    request = QNetworkRequest(QUrl(url))
    reply = QgsNetworkAccessManager.instance().get(request)

    canceled = {"value": False}

    loop = QEventLoop()
    reply.finished.connect(loop.quit)

    # アイドルタイムアウト: 受信のたびに測り直すので、進んでいる限り発火しない。
    idle_timer = QTimer(reply)
    idle_timer.setSingleShot(True)
    idle_timer.timeout.connect(reply.abort)
    reply.finished.connect(idle_timer.stop)

    def check_canceled() -> bool:
        if is_canceled is not None and is_canceled():
            canceled["value"] = True
            reply.abort()
            return True
        return False

    def on_ready_read() -> None:
        # データ到着の都度キャンセルを見るので、巨大ファイルでも素早く中断できる。
        if check_canceled():
            return
        # 届いた分だけ逐次ファイルへ書き出し、reply 内のバッファを空にする。
        out.write(reply.readAll())

    def on_progress(received: int, total: int) -> None:
        idle_timer.start(_IDLE_TIMEOUT_MS)
        if check_canceled():
            return
        if progress_callback is not None and total > 0:
            progress_callback(received / total * 100.0)

    reply.readyRead.connect(on_ready_read)
    reply.downloadProgress.connect(on_progress)
    idle_timer.start(_IDLE_TIMEOUT_MS)
    exec_event_loop(loop)

    # 受信済みの残りを書き切ってからファイルを閉じる。
    out.write(reply.readAll())
    out.close()

    def _fail(message: str) -> None:
        reply.deleteLater()
        QFile.remove(dest_path)
        raise Exception(message)

    if canceled["value"]:
        reply.deleteLater()
        QFile.remove(dest_path)
        raise DownloadCanceled()

    if not reply.isFinished():
        reply.abort()
        _fail("Download failed: reply did not finish")

    # HTTP 応答を受け取れたかどうかで層を分ける。reply.error() は HTTP 4xx/5xx でも
    # 非 NoError になるため、status_code の有無でネットワーク層とアプリ層を切り分ける。
    status_code = reply.attribute(Q_NETWORK_REQUEST_ATTRIBUTE.HttpStatusCodeAttribute)
    if status_code is None:
        network_error = reply.error()
        error_string = reply.errorString()
        _fail(f"Download failed (network error {int(network_error)}): {error_string}")
    if status_code not in (200, 206):
        _fail(f"Download failed (HTTP {status_code})")

    reply.deleteLater()
