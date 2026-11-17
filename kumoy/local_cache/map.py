"""Map files left by plugin versions before the "kumoy" project storage.

Those versions opened a map by writing its XML to ``<cache dir>/<map id>.qgs``
and opening that file. Nothing is written here anymore: the files are only
recognized (to open the map from Kumoy instead, see ui/project_storage.py),
measured and deleted by the cache-clearing UI.
"""

import os
import shutil
from typing import Optional

from qgis.core import Qgis, QgsApplication, QgsMessageLog

from ..constants import LOG_CATEGORY
from .size import dir_total_size, files_total_size


def get_cache_dir() -> str:
    return os.path.join(
        QgsApplication.qgisSettingsDirPath(), "kumoygis", "local_cache", "maps"
    )


def get_filepath(map_id: str) -> str:
    return os.path.join(get_cache_dir(), f"{map_id}.qgs")


def legacy_map_id(path: str) -> Optional[str]:
    """The map ID when path is a map file of the old cache, else None."""
    if not path or not path.lower().endswith(".qgs"):
        return None
    directory, name = os.path.split(os.path.abspath(path))
    if os.path.normcase(directory) != os.path.normcase(
        os.path.abspath(get_cache_dir())
    ):
        return None
    return os.path.splitext(name)[0] or None


def _entries():
    try:
        return list(os.scandir(get_cache_dir()))
    except FileNotFoundError:
        return []


def get_cache_size(map_id: str) -> int:
    """Size in bytes of the map's files (any file whose name contains map_id)."""
    return files_total_size(
        e.path for e in _entries() if map_id in e.name and e.is_file()
    )


def get_total_cache_size() -> int:
    cache_dir = get_cache_dir()
    return dir_total_size(cache_dir) if os.path.isdir(cache_dir) else 0


def _remove(entry: os.DirEntry) -> bool:
    try:
        if entry.is_dir(follow_symlinks=False):
            shutil.rmtree(entry.path)
        else:
            os.unlink(entry.path)
        return True
    except OSError as e:
        # A file open in another program (Windows) cannot be deleted
        QgsMessageLog.logMessage(
            f"Could not delete {entry.path}: {e}", LOG_CATEGORY, Qgis.Warning
        )
        return False


def clear(map_id: str) -> bool:
    """Delete the map's files. True when nothing is left."""
    results = [_remove(e) for e in _entries() if map_id in e.name]
    return all(results)


def clear_all() -> bool:
    results = [_remove(e) for e in _entries()]
    return all(results)
