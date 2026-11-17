"""kumoy.download: streaming download, cache fill and background fetches."""

import http.server
import os
import threading
import time

import pytest

PAYLOAD = b"COG raster bytes " * 10_000  # spans several readyRead chunks


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/ok":
            self.send_response(200)
            self.send_header("Content-Length", str(len(PAYLOAD)))
            self.end_headers()
            self.wfile.write(PAYLOAD)
        elif self.path == "/truncated":
            # Connection lost mid-body: the status line already said 200
            self.send_response(200)
            self.send_header("Content-Length", str(len(PAYLOAD)))
            self.end_headers()
            self.wfile.write(PAYLOAD[:1000])
            self.close_connection = True
        else:
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    host, port = httpd.server_address
    yield f"http://{host}:{port}"
    httpd.shutdown()


@pytest.fixture
def download(qgis_app, tmp_path, monkeypatch):
    from plugin_dir.kumoy import download
    from plugin_dir.kumoy.local_cache import raster

    cache_dir = tmp_path / "rasters"
    cache_dir.mkdir()
    monkeypatch.setattr(raster, "_get_cache_dir", lambda: str(cache_dir))
    return download


def wait_until(condition, timeout=10.0):
    from qgis.PyQt.QtCore import QCoreApplication

    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        QCoreApplication.processEvents()
        time.sleep(0.01)


class TestDownloadToFile:
    def test_streams_to_file_in_worker_thread(self, download, server, tmp_path):
        from plugin_dir.kumoy.tasks import run_task

        dest = str(tmp_path / "out.tif")
        progress, done = [], []
        run_task(
            "dl",
            lambda t: download.download_to_file(f"{server}/ok", dest, progress.append),
            done.append,
            done.append,
        )
        wait_until(lambda: done)

        assert done == [None]
        assert open(dest, "rb").read() == PAYLOAD
        assert progress[-1] == pytest.approx(100.0)

    def test_http_error_leaves_no_file(self, download, server, tmp_path):
        from plugin_dir.kumoy.api.error import AppError

        dest = str(tmp_path / "missing.tif")
        with pytest.raises(AppError, match="HTTP 403"):
            download.download_to_file(f"{server}/expired", dest)
        assert not os.path.exists(dest)

    def test_truncated_body_is_an_error(self, download, server, tmp_path):
        from plugin_dir.kumoy.api.error import NetworkError

        dest = str(tmp_path / "truncated.tif")
        with pytest.raises(NetworkError):
            download.download_to_file(f"{server}/truncated", dest)
        assert not os.path.exists(dest)

    def test_cancel_leaves_no_file(self, download, server, tmp_path):
        from plugin_dir.kumoy.tasks import Canceled

        dest = str(tmp_path / "canceled.tif")
        with pytest.raises(Canceled):
            download.download_to_file(f"{server}/ok", dest, is_canceled=lambda: True)
        assert not os.path.exists(dest)


class TestDownloadRaster:
    def test_downloads_once_into_cache(self, download, server, monkeypatch):
        from plugin_dir.kumoy.local_cache import raster

        urls = []
        monkeypatch.setattr(
            download.api.raster,
            "get_download_url",
            lambda rid: urls.append(rid) or f"{server}/ok",
        )

        path = download.download_raster("r-1")
        assert download.download_raster("r-1") == path  # cached: no request

        assert urls == ["r-1"]
        assert open(path, "rb").read() == PAYLOAD
        assert os.listdir(os.path.dirname(path)) == ["r-1.tif"]
        assert raster.is_cached("r-1")

    def test_failure_leaves_no_cache_entry(self, download, server, monkeypatch):
        from plugin_dir.kumoy.api.error import AppError

        monkeypatch.setattr(
            download.api.raster, "get_download_url", lambda rid: f"{server}/x"
        )
        with pytest.raises(AppError):
            download.download_raster("r-2")
        path = download.local_cache.raster.get_cache_path("r-2")
        assert os.listdir(os.path.dirname(path)) == []


class TestFetchRaster:
    @pytest.fixture
    def slow_download(self, download, monkeypatch):
        """download_raster stand-in that waits for `release` and counts calls."""
        state = {"calls": 0, "release": threading.Event(), "fail": None}

        def fake(raster_id, progress_callback=None, is_canceled=None):
            state["calls"] += 1
            while not state["release"].wait(0.05):
                if is_canceled():
                    from plugin_dir.kumoy.tasks import Canceled

                    raise Canceled()
            if state["fail"]:
                raise state["fail"]
            path = download.local_cache.raster.get_cache_path(raster_id)
            open(path, "wb").close()
            return path

        monkeypatch.setattr(download, "download_raster", fake)
        return state

    def test_concurrent_requests_share_one_download(self, download, slow_download):
        ready, called = [], []
        download.fetcher.ready.connect(ready.append)
        try:
            download.fetch_raster("r-1", "dem", lambda: called.append(1))
            download.fetch_raster("r-1", "dem", lambda: called.append(2))
            download.fetch_raster("r-1", "dem")
            slow_download["release"].set()
            wait_until(lambda: ready)
        finally:
            download.fetcher.ready.disconnect(ready.append)

        assert slow_download["calls"] == 1
        assert ready == ["r-1"]
        assert called == [1, 2]

    def test_cached_calls_back_at_once(self, download, slow_download):
        open(download.local_cache.raster.get_cache_path("r-1"), "wb").close()
        called = []

        download.fetch_raster("r-1", "dem", lambda: called.append(1))

        assert called == [1]
        assert slow_download["calls"] == 0

    def test_request_from_worker_thread(self, download, slow_download):
        called = []
        slow_download["release"].set()

        t = threading.Thread(
            target=download.fetch_raster, args=("r-1", "dem", lambda: called.append(1))
        )
        t.start()
        t.join()
        wait_until(lambda: called)

        assert slow_download["calls"] == 1

    def test_failure_is_broadcast_and_retry_starts_again(self, download, slow_download):
        failed = []
        download.fetcher.failed.connect(lambda *args: failed.append(args))
        slow_download["fail"] = RuntimeError("boom")
        slow_download["release"].set()

        download.fetch_raster("r-1", "dem")
        wait_until(lambda: failed)
        assert failed[0][:2] == ("r-1", "dem")
        assert str(failed[0][2]) == "boom"

        slow_download["fail"] = None
        called = []
        download.fetch_raster("r-1", "dem", lambda: called.append(1))
        wait_until(lambda: called)
        assert slow_download["calls"] == 2

    def test_cancel_is_silent_and_forgotten(self, download, slow_download):
        from qgis.core import QgsApplication

        failed, called = [], []
        download.fetcher.failed.connect(lambda *args: failed.append(args))
        download.fetch_raster("r-1", "dem", lambda: called.append(1))
        wait_until(lambda: slow_download["calls"] == 1)

        for task in QgsApplication.taskManager().activeTasks():
            task.cancel()
        wait_until(lambda: not QgsApplication.taskManager().activeTasks())
        wait_until(lambda: "r-1" not in download.fetcher._waiting)
        assert failed == [] and called == []

        slow_download["release"].set()
        download.fetch_raster("r-1", "dem", lambda: called.append(2))
        wait_until(lambda: called)
        assert called == [2]
