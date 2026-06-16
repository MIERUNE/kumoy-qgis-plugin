"""kumoy/download.py のテスト

ローカル HTTP サーバを立て、download_to_file が reply をファイルへストリーミング
保存できること、HTTP エラー時に書きかけを残さないことを検証する。
"""

import http.server
import os
import threading

import pytest

PAYLOAD = b"COG raster bytes " * 10_000  # ~170KB（複数 readyRead を跨ぐ程度）


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/ok":
            self.send_response(200)
            self.send_header("Content-Length", str(len(PAYLOAD)))
            self.end_headers()
            self.wfile.write(PAYLOAD)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    yield f"http://{host}:{port}"
    httpd.shutdown()


@pytest.mark.usefixtures("qgis_plugin_path")
class TestDownloadToFile:
    def _mod(self):
        from plugin_dir.kumoy import download

        return download

    def test_streams_to_file(self, server, tmp_path):
        download = self._mod()
        dest = str(tmp_path / "out.tif")
        progress = []

        download.download_to_file(
            f"{server}/ok", dest, progress_callback=progress.append
        )

        with open(dest, "rb") as f:
            assert f.read() == PAYLOAD
        # 進捗が最後まで進んでいる
        assert progress and progress[-1] == pytest.approx(100.0)

    def test_http_error_leaves_no_file(self, server, tmp_path):
        download = self._mod()
        dest = str(tmp_path / "missing.tif")

        with pytest.raises(Exception, match="HTTP 404"):
            download.download_to_file(f"{server}/nope", dest)

        assert not os.path.exists(dest)

    def test_cancel_leaves_no_file(self, server, tmp_path):
        download = self._mod()
        dest = str(tmp_path / "cancelled.tif")

        with pytest.raises(download.DownloadCanceled):
            download.download_to_file(f"{server}/ok", dest, is_canceled=lambda: True)

        assert not os.path.exists(dest)
