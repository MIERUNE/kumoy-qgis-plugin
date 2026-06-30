import os
import tempfile
from typing import Optional

from qgis.core import Qgis, QgsApplication, QgsMessageLog, QgsProject

from ... import i18n
from ..constants import LOG_CATEGORY
from ..sprite import pin_fixed_aspect_ratios

# Flag to prevent double updates when handling the project saved event.
# When serialize_project() writes the QGIS project to disk, this guards against
# re-entrancy via the QgsProject.projectSaved signal.
is_updating = False

# Maximum size (in characters) of a serialized project the server accepts.
LENGTH_LIMIT = 3000000  # 3 million characters


def get_cache_dir() -> str:
    """Return the directory where map cache files (.qgs) are stored."""
    setting_dir = QgsApplication.qgisSettingsDirPath()
    cache_dir = os.path.join(setting_dir, "kumoygis", "local_cache", "maps")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def get_filepath(map_id: str) -> str:
    """Retrieve a cached map path."""
    cache_dir = get_cache_dir()
    cache_file = os.path.join(cache_dir, f"{map_id}.qgs")
    return cache_file


def clear(map_id: str) -> bool:
    """Clear cache for a specific map.
    Returns True if all files were deleted successfully, False otherwise.
    """
    cache_dir = get_cache_dir()
    success = True
    # Remove all files containing map_id in their names
    for filename in os.listdir(cache_dir):
        if map_id in filename:
            file_path = os.path.join(cache_dir, filename)
            try:
                os.unlink(file_path)
            except PermissionError as e:
                QgsMessageLog.logMessage(
                    f"Ignored file access error for {file_path}: {e}",
                    LOG_CATEGORY,
                    Qgis.Info,
                )
                success = False  # Flag unsucceed deletion
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Unexpected error for {file_path}: {e}",
                    LOG_CATEGORY,
                    Qgis.Critical,
                )
                success = False  # Flag unsucceed

    return success


def clear_all() -> bool:
    """Clear all cached map files. Returns True if all files were deleted successfully."""

    cache_dir = get_cache_dir()
    success = True

    # Remove all files in cache directory
    for filename in os.listdir(cache_dir):
        file_path = os.path.join(cache_dir, filename)
        try:
            os.unlink(file_path)
        except PermissionError as e:
            # Ignore Permission denied error and continue
            QgsMessageLog.logMessage(
                f"Ignored file access error: {e}",
                LOG_CATEGORY,
                Qgis.Info,
            )
            success = False  # Flag unsucceed deletion
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Unexpected error for {file_path}: {e}",
                LOG_CATEGORY,
                Qgis.Critical,
            )
            success = False  # Flag unsucceed

    return success


def serialize_project() -> str:
    """Serialize the current project to an XML string via a throwaway temp file.

    The canonical cache file and the project state (fileName / dirty) are left
    untouched — use commit_to_cache() to persist after a successful upload.

    The temp file is created in the cache directory so QGIS resolves relative
    layer paths exactly as it would for the real cache file. Projects may keep
    local (unsupported) layers whose file paths must round-trip correctly, so
    serializing elsewhere (e.g. the system temp dir) would rewrite those paths.

    QgsProject.write() changes fileName and clears the dirty flag, so we
    snapshot and restore both to hide that side effect from callers.
    """
    global is_updating
    project = QgsProject.instance()
    pin_fixed_aspect_ratios(project)

    prev_name = project.fileName()
    prev_dirty = project.isDirty()
    # Force .qgs (plain XML) — .qgz would be compressed.
    fd, tmp_path = tempfile.mkstemp(suffix=".qgs", dir=get_cache_dir())
    os.close(fd)
    is_updating = True
    try:
        project.write(tmp_path)
        with open(tmp_path, "r", encoding="utf-8") as f:
            return f.read()
    finally:
        is_updating = False
        project.setFileName(prev_name)
        project.setDirty(prev_dirty)
        try:
            os.remove(tmp_path)
        except OSError as e:
            QgsMessageLog.logMessage(
                f"Failed to remove temp project file {tmp_path}: {e}",
                LOG_CATEGORY,
                Qgis.Info,
            )


def size_limit_error(qgs_str: str) -> Optional[str]:
    """Return an error message if the serialized project exceeds the size limit.

    Returns None when within the limit. Returning a message (instead of raising)
    lets callers validate without wrapping the call in try/except. A warning is
    also logged when over the limit.
    """
    actual_length = len(qgs_str)
    if actual_length <= LENGTH_LIMIT:
        return None

    err = i18n.tr(
        "Project file size is too large. Limit is {} bytes. your: {} bytes"
    ).format(LENGTH_LIMIT, actual_length)
    QgsMessageLog.logMessage(
        err,
        LOG_CATEGORY,
        Qgis.Warning,
    )
    return err


def commit_to_cache(map_id: str, qgs_str: str) -> None:
    """Persist a successfully-uploaded project to the cache (keeps cache == server)."""
    with open(get_filepath(map_id), "w", encoding="utf-8") as f:
        f.write(qgs_str)
