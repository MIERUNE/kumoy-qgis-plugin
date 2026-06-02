import os

from qgis.core import Qgis, QgsApplication, QgsMessageLog, QgsProject

from ...i18n import tr
from ..constants import LOG_CATEGORY
from ..sprite import pin_fixed_aspect_ratios

# Flag to prevent double updates when handling project saved event.
# write_qgsfile() で QGIS プロジェクトをディスクに書き出す際、
# QgsProject.projectSaved シグナル経由で再入することを防ぐためのフラグ。
is_updating = False


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


def write_qgsfile(map_id: str) -> str:
    """Save current project to local cache and return project file content as string."""
    global is_updating
    is_updating = True
    try:
        map_path = get_filepath(map_id)
        project = QgsProject.instance()
        pin_fixed_aspect_ratios(project)
        project.write(map_path)
        qgisproject_str = _get_qgs_str(map_path)
    finally:
        is_updating = False
    return qgisproject_str


def _get_qgs_str(map_path: str) -> str:
    """
    Get Qgs project file content as string.

    Args:
        file_path (str): QGS project file path

    Raises:
        Exception: too large file size

    Returns:
        str: Qgs project file content
    """

    with open(map_path, "r", encoding="utf-8") as f:
        qgs_str = f.read()

    # Character length limit check
    LENGTH_LIMIT = 3000000  # 300万文字
    actual_length = len(qgs_str)
    if actual_length > LENGTH_LIMIT:
        err = tr(
            "Project file size is too large. Limit is {} bytes. your: {} bytes"
        ).format(LENGTH_LIMIT, actual_length)
        QgsMessageLog.logMessage(
            err,
            LOG_CATEGORY,
            Qgis.Warning,
        )
        raise Exception(err)

    return qgs_str
