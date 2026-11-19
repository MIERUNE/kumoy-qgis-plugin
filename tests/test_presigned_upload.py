"""kumoy.upload.presigned: PUT streaming and multipart POST.

The PUT tests guard the response-wait phase: after the last byte S3 may take
minutes to answer with no progress events, and QgsNetworkAccessManager's own
idle timeout (60 s by default) would abort a successful upload.
"""

import http.server
import threading
import time
from email.parser import BytesParser
from email.policy import HTTP

import pytest


class _Handler(http.server.BaseHTTPRequestHandler):
    response_delay_sec = 0.0
    status = 200
    received = []

    def _read(self):
        return self.rfile.read(int(self.headers.get("Content-Length", 0)))

    def _answer(self, body=b""):
        time.sleep(self.response_delay_sec)
        self.send_response(self.status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_PUT(self):
        type(self).received.append((self.headers["Content-Type"], self._read()))
        self._answer(
            b"<Error>SignatureDoesNotMatch</Error>" if self.status >= 400 else b""
        )

    def do_POST(self):
        type(self).received.append((self.headers["Content-Type"], self._read()))
        self._answer()

    def log_message(self, *args):
        pass


@pytest.fixture
def server(qgis_app):
    _Handler.response_delay_sec = 0.0
    _Handler.status = 200
    _Handler.received = []
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


@pytest.fixture
def upload_file(tmp_path):
    path = tmp_path / "upload.bin"
    path.write_bytes(b"x" * (256 * 1024))
    return str(path)


@pytest.fixture
def short_qgis_network_timeout():
    from qgis.core import QgsNetworkAccessManager

    original = QgsNetworkAccessManager.timeout()
    QgsNetworkAccessManager.setTimeout(1000)
    yield
    QgsNetworkAccessManager.setTimeout(original)


def test_put_streams_file_from_worker_thread(server, upload_file):
    from qgis.PyQt.QtCore import QCoreApplication

    from plugin_dir.kumoy.tasks import run_task
    from plugin_dir.kumoy.upload.presigned import upload_file_to_presigned_put

    progress, done = [], []
    run_task(
        "up",
        lambda t: upload_file_to_presigned_put(
            f"{server}/obj", upload_file, "image/tiff", progress.append
        ),
        done.append,
        done.append,
    )
    deadline = time.monotonic() + 10
    while not done and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)

    assert done == [None]
    assert _Handler.received == [("image/tiff", b"x" * (256 * 1024))]
    assert progress[-1] == pytest.approx(100.0)


def test_put_survives_qgis_network_timeout(
    server, upload_file, short_qgis_network_timeout
):
    from plugin_dir.kumoy.upload.presigned import upload_file_to_presigned_put

    _Handler.response_delay_sec = 3.0  # longer than QGIS's (shortened) timeout

    upload_file_to_presigned_put(f"{server}/obj", upload_file, "image/tiff")


def test_put_cancel_works_while_waiting_for_response(server, upload_file):
    from plugin_dir.kumoy.tasks import Canceled
    from plugin_dir.kumoy.upload.presigned import (
        UploadCanceled,
        upload_file_to_presigned_put,
    )

    _Handler.response_delay_sec = 10.0
    started = time.monotonic()

    with pytest.raises(UploadCanceled) as info:
        upload_file_to_presigned_put(
            f"{server}/obj",
            upload_file,
            "image/tiff",
            is_canceled=lambda: time.monotonic() - started > 1.0,
        )

    assert time.monotonic() - started < 5.0
    # run_task treats it as a cancel, not an error
    assert isinstance(info.value, Canceled)


def test_put_error_carries_s3_message(server, upload_file):
    from plugin_dir.kumoy.api.error import AppError
    from plugin_dir.kumoy.upload.presigned import upload_file_to_presigned_put

    _Handler.status = 403

    with pytest.raises(AppError, match="HTTP 403") as info:
        upload_file_to_presigned_put(f"{server}/obj", upload_file, "image/tiff")
    assert "SignatureDoesNotMatch" in info.value.error


def test_post_sends_fields_then_file(server):
    from plugin_dir.kumoy.upload.presigned import upload_bytes_to_presigned_post

    upload_bytes_to_presigned_post(
        f"{server}/bucket",
        {"key": "sprites/a.png", "Content-Type": "image/png", "Policy": "p"},
        b"\x89PNG\r\n--not-a-boundary",
    )

    [(content_type, body)] = _Handler.received
    message = BytesParser(policy=HTTP).parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body
    )
    parts = list(message.iter_parts())
    names = [p.get_param("name", header="content-disposition") for p in parts]
    assert names == ["key", "Content-Type", "Policy", "file"]  # file last for S3
    assert parts[0].get_payload(decode=True) == b"sprites/a.png"
    assert parts[-1].get_content_type() == "image/png"
    assert parts[-1].get_payload(decode=True) == b"\x89PNG\r\n--not-a-boundary"


def test_post_error_raises(server):
    from plugin_dir.kumoy.api.error import AppError
    from plugin_dir.kumoy.upload.presigned import upload_bytes_to_presigned_post

    _Handler.status = 403

    with pytest.raises(AppError):
        upload_bytes_to_presigned_post(f"{server}/bucket", {"key": "k"}, b"data")
