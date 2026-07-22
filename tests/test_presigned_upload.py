"""presigned PUT アップロードの応答待ちフェーズの挙動テスト。

全バイト送信後、S3 互換サーバが応答を返すまでの「応答待ち」中は進捗イベントが
一切来ない。QgsNetworkAccessManager の無通信タイムアウト（デフォルト60秒）が
この間に reply を abort してしまう問題の回帰テスト。
"""

import http.server
import threading
import time
from pathlib import Path
from typing import Any, Iterator

import pytest
from qgis.core import QgsNetworkAccessManager


class _DelayedPutHandler(http.server.BaseHTTPRequestHandler):
    """PUT の全ボディ受信後、指定秒だけ待ってから 200 を返す。"""

    response_delay_sec: float = 0.0

    def do_PUT(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        time.sleep(self.response_delay_sec)
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def delayed_server() -> Iterator[int]:
    server = http.server.HTTPServer(("127.0.0.1", 0), _DelayedPutHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_port
    server.shutdown()


@pytest.fixture
def upload_file(tmp_path: Path) -> str:
    path = tmp_path / "upload.bin"
    path.write_bytes(b"x" * (256 * 1024))
    return str(path)


@pytest.fixture
def short_qgis_network_timeout() -> Iterator[None]:
    """QGIS側の無通信タイムアウトをテスト用に短縮し、終了後に復元する。"""
    original = QgsNetworkAccessManager.timeout()
    QgsNetworkAccessManager.setTimeout(1000)
    yield
    QgsNetworkAccessManager.setTimeout(original)


class TestResponseWaitPhase:
    def test_survives_qgis_network_timeout(
        self,
        qgis_app: Any,
        short_qgis_network_timeout: None,
        delayed_server: int,
        upload_file: str,
    ) -> None:
        """応答待ちが QGIS の無通信タイムアウトより長くても完走すること。"""
        from plugin_dir.kumoy.upload.presigned import upload_file_to_presigned_put

        _DelayedPutHandler.response_delay_sec = 3.0

        upload_file_to_presigned_put(
            url=f"http://127.0.0.1:{delayed_server}/obj",
            file_path=upload_file,
            content_type="application/octet-stream",
        )

    def test_cancel_works_during_response_wait(
        self,
        qgis_app: Any,
        delayed_server: int,
        upload_file: str,
    ) -> None:
        """応答待ち中（進捗イベントが来ない間）でも Cancel が効くこと。"""
        from plugin_dir.kumoy.upload.presigned import (
            UploadCanceled,
            upload_file_to_presigned_put,
        )

        _DelayedPutHandler.response_delay_sec = 10.0
        started = time.monotonic()

        with pytest.raises(UploadCanceled):
            upload_file_to_presigned_put(
                url=f"http://127.0.0.1:{delayed_server}/obj",
                file_path=upload_file,
                content_type="application/octet-stream",
                is_canceled=lambda: time.monotonic() - started > 1.0,
            )

        # 応答(10秒後)を待たずに中断できている。
        assert time.monotonic() - started < 5.0
