"""Download raster COGs into the local cache.

The transfer functions block and belong in a worker thread (kumoy.tasks):
they wait on a local QEventLoop, which on the main thread would re-enter the
UI. `fetch_raster` is the non-blocking entry point for the main thread.
"""

from typing import Callable, Dict, List, Optional

from qgis.core import QgsNetworkAccessManager
from qgis.PyQt.QtCore import QCoreApplication, QFile, QObject, QUrl, pyqtSignal
from qgis.PyQt.QtNetwork import QNetworkRequest

from .. import i18n
from ..pyqt_version import Q_IODEVICE_OPEN_MODE, Q_NETWORK_REQUEST_ATTRIBUTE
from . import api, local_cache
from .tasks import Canceled, run_task
from .shared import shared
from .upload.presigned import (
    IsCanceledCallback,
    ProgressCallback,
    raise_for_status,
    wait_for_reply,
)


def download_to_file(
    url: str,
    dest_path: str,
    progress_callback: Optional[ProgressCallback] = None,
    is_canceled: Optional[IsCanceledCallback] = None,
) -> None:
    """Stream `url` into `dest_path` (worker thread).

    Written as it arrives, so multi-GB files never sit in memory (Qt5's
    QByteArray tops out at 2 GB). On failure or cancel (`Canceled`) the file
    is removed.
    """
    out = QFile(dest_path)
    if not out.open(Q_IODEVICE_OPEN_MODE.WriteOnly):
        raise OSError(f"Cannot write {dest_path}: {out.errorString()}")

    request = QNetworkRequest(QUrl(url))
    # Keep gigabytes out of QGIS's network disk cache; the URL is single-use
    request.setAttribute(Q_NETWORK_REQUEST_ATTRIBUTE.CacheSaveControlAttribute, False)
    reply = QgsNetworkAccessManager.instance().get(request)
    write_failed = []

    def write() -> None:
        # A short write (disk full) must not end up as a truncated cache file
        data = reply.readAll()
        if out.write(data) != len(data):
            write_failed.append(out.errorString())
            reply.abort()

    reply.readyRead.connect(write)
    try:
        canceled = wait_for_reply(
            reply, reply.downloadProgress, progress_callback, is_canceled
        )
        write()
        out.close()
        if canceled:
            raise Canceled()
        if write_failed:
            raise OSError(f"Cannot write {dest_path}: {write_failed[0]}")
        raise_for_status(reply, "Download")
    except BaseException:
        out.close()
        QFile.remove(dest_path)
        raise
    finally:
        reply.deleteLater()


def download_raster(
    raster_id: str,
    progress_callback: Optional[ProgressCallback] = None,
    is_canceled: Optional[IsCanceledCallback] = None,
) -> str:
    """Download the raster's COG into the cache unless there; return its path.

    Worker thread only. A partial file never becomes the cache entry.
    """
    if local_cache.raster.is_cached(raster_id):
        return local_cache.raster.get_cache_path(raster_id)
    url = api.raster.get_download_url(raster_id)
    part_path = local_cache.raster.new_part_path(raster_id)
    download_to_file(url, part_path, progress_callback, is_canceled)
    return local_cache.raster.commit(raster_id, part_path)


class RasterFetcher(QObject):
    """Background downloads into the cache, at most one task per raster."""

    # The raster's COG is now cached
    ready = pyqtSignal(str)
    # (raster_id, raster_name, exception); not emitted on cancel
    failed = pyqtSignal(str, str, object)
    # Requests from any thread are queued to the main thread, where the task
    # bookkeeping and callbacks live
    _request = pyqtSignal(str, str, object)

    def __init__(self) -> None:
        super().__init__()
        app = QCoreApplication.instance()
        if app is not None:
            self.moveToThread(app.thread())
        self._waiting: Dict[str, List[Callable[[], None]]] = {}
        self._request.connect(self._fetch)

    def _fetch(
        self, raster_id: str, name: str, on_ready: Optional[Callable[[], None]]
    ) -> None:
        if local_cache.raster.is_cached(raster_id):
            if on_ready is not None:
                on_ready()
            return
        if raster_id in self._waiting:
            if on_ready is not None:
                self._waiting[raster_id].append(on_ready)
            return
        self._waiting[raster_id] = [on_ready] if on_ready is not None else []

        def succeeded(_path: str) -> None:
            callbacks = self._waiting.pop(raster_id, [])
            self.ready.emit(raster_id)
            for callback in callbacks:
                callback()

        task = run_task(
            i18n.tr("Downloading raster '{}'").format(name),
            lambda t: download_raster(raster_id, t.setProgress, t.isCanceled),
            succeeded,
            lambda e: self.failed.emit(raster_id, name, e),
            can_cancel=True,
        )
        # Canceled and failed tasks never call succeeded(); forget them so the
        # next request starts a new download
        task.taskTerminated.connect(lambda: self._waiting.pop(raster_id, None))


fetcher = shared("raster_fetcher", RasterFetcher)


def fetch_raster(
    raster_id: str, raster_name: str, on_ready: Optional[Callable[[], None]] = None
) -> None:
    """Make sure the raster gets cached, downloading it in a QgsTask.

    Callable from any thread; never blocks. `on_ready` runs on the main thread
    once the COG is cached (right away when it already is). Concurrent requests
    share one download. Outcomes are also broadcast by `fetcher.ready` /
    `fetcher.failed`; cancel is silent.
    """
    fetcher._request.emit(raster_id, raster_name, on_ready)
