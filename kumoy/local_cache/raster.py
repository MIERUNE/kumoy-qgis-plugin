"""Local cache of raster COGs: one `{raster_id}.tif` per raster.

A raster's COG never changes after upload (a new upload gets a new id), so a
cached file is valid forever and needs no sync. File operations only; the
download lives in kumoy/download.py.
"""

import glob
import os
import shutil
import tempfile

from qgis.core import QgsApplication


def _get_cache_dir() -> str:
    cache_dir = os.path.join(
        QgsApplication.qgisSettingsDirPath(), "kumoygis", "local_cache", "rasters"
    )
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def get_cache_path(raster_id: str) -> str:
    """Path of the raster's cached COG (whether it exists or not)."""
    return os.path.join(_get_cache_dir(), f"{raster_id}.tif")


def is_cached(raster_id: str) -> bool:
    return os.path.exists(get_cache_path(raster_id))


def new_part_path(raster_id: str) -> str:
    """Create an empty partial file for a download of `raster_id`.

    Unique per call so two downloads of the same raster never write into the
    same file. It sits in the cache dir so that commit() is a same-filesystem
    atomic rename, and clear() can find it.
    """
    fd, path = tempfile.mkstemp(
        prefix=f"{raster_id}.tif.", suffix=".part", dir=_get_cache_dir()
    )
    os.close(fd)
    return path


def commit(raster_id: str, part_path: str) -> str:
    """Turn a complete partial file into the cache entry and return its path."""
    cache_path = get_cache_path(raster_id)
    if os.path.exists(cache_path):
        # Another download won the race. The content is identical, and
        # replacing a file GDAL holds open fails on Windows.
        os.remove(part_path)
    else:
        os.replace(part_path, cache_path)
    return cache_path


def store(raster_id: str, src_path: str) -> str:
    """Move a local COG (e.g. the one just uploaded) into the cache.

    `src_path` is consumed. The temp dir may be on another filesystem, so the
    move goes through a partial file to keep the final rename atomic.
    """
    part_path = new_part_path(raster_id)
    shutil.move(src_path, part_path)
    return commit(raster_id, part_path)


def _files(raster_id: str) -> list:
    cache_path = get_cache_path(raster_id)
    return [cache_path] + glob.glob(glob.escape(cache_path) + ".*.part")


def get_cache_size(raster_id: str) -> int:
    """Bytes used by the raster's cache, partial downloads included."""
    return sum(os.path.getsize(p) for p in _files(raster_id) if os.path.isfile(p))


def get_total_cache_size() -> int:
    total = 0
    for root, _dirs, files in os.walk(_get_cache_dir()):
        total += sum(os.path.getsize(os.path.join(root, f)) for f in files)
    return total


def clear(raster_id: str) -> bool:
    """Delete the raster's cache. True when nothing is left behind."""
    success = True
    for path in _files(raster_id):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            success = False  # e.g. held open by a layer on Windows
    return success


def clear_all() -> bool:
    success = True
    for entry in list(os.scandir(_get_cache_dir())):
        try:
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path)
            else:
                os.remove(entry.path)
        except OSError:
            success = False
    return success
