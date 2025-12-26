import os

from qgis.core import Qgis, QgsApplication, QgsMessageLog, QgsProject
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QMessageBox

from ..constants import LOG_CATEGORY

from .. import api
from ..api.error import format_api_error

from qgis.utils import iface


from ...pyqt_version import Q_MESSAGEBOX_STD_BUTTON

# Flag to prevent double updates when handling project saved event
is_updating = False


def tr(message: str, context: str = "@default") -> str:
    return QCoreApplication.translate(context, message)


def _get_cache_dir() -> str:
    """Return the directory where cache files are stored.
    data_type: subdirectory name maps or vectors"""
    setting_dir = QgsApplication.qgisSettingsDirPath()
    cache_dir = os.path.join(setting_dir, "kumoygis", "local_cache", "maps")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def get_filepath(map_id: str) -> str:
    """Retrieve a cached map path."""
    cache_dir = _get_cache_dir()
    cache_file = os.path.join(cache_dir, f"{map_id}.qgs")
    return cache_file


def clear(map_id: str) -> bool:
    """Clear cache for a specific map.
    Returns True if all files were deleted successfully, False otherwise.
    """
    cache_dir = _get_cache_dir()
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

    cache_dir = _get_cache_dir()
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


def handle_project_saved() -> None:
    """Update current project to Kumoy when QGIS project is saved"""
    # Do not proceed if already updating from styled map item
    if is_updating:
        return

    project = QgsProject.instance()

    # Get styled map ID from custom variables
    custom_vars = project.customVariables()
    styled_map_id = custom_vars.get("kumoy_map_id")

    # Case of non kumoy map
    if not styled_map_id:
        return

    # Check if project file is saved in local cache
    file_path = os.path.abspath(project.absoluteFilePath())
    local_cache_dir = os.path.abspath(_get_cache_dir())

    try:
        in_cache = os.path.commonpath([file_path, local_cache_dir]) == local_cache_dir
    except ValueError:
        in_cache = False

    # Clear custom variables and don't proceed if the project file not saved in local cache
    if not in_cache:
        QgsProject.instance().setCustomVariables({})
        return

    try:
        styled_map_detail = api.styledmap.get_styled_map(styled_map_id)
    except Exception as e:
        error_text = format_api_error(e)
        QgsMessageLog.logMessage(
            tr("Error loading map: {}").format(error_text),
            LOG_CATEGORY,
            Qgis.Critical,
        )
        QMessageBox.critical(
            None,
            tr("Error"),
            tr("Error loading map: {}").format(error_text),
        )
        return

    # don't process if role cannot edit
    if styled_map_detail.role not in ["ADMIN", "OWNER"]:
        iface.messageBar().pushMessage(
            tr("Failed"),
            tr("You do not have permission to save this map to Kumoy."),
        )
        return

    # Check dialog
    confirm = QMessageBox.question(
        None,
        tr("Save Map"),
        tr(
            "Are you sure you want to overwrite the map '{}' with the current project state?"
        ).format(styled_map_detail.name),
        Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
        Q_MESSAGEBOX_STD_BUTTON.No,
    )
    if confirm != Q_MESSAGEBOX_STD_BUTTON.Yes:
        return

    try:
        qgsproject_str = _get_qgs_str(file_path)

        # Overwrite styled map
        updated_styled_map = api.styledmap.update_styled_map(
            styled_map_id,
            api.styledmap.UpdateStyledMapOptions(
                qgisproject=qgsproject_str,
            ),
        )
    except Exception as e:
        error_text = format_api_error(e)
        QgsMessageLog.logMessage(
            tr("Error saving map: {}").format(error_text),
            LOG_CATEGORY,
            Qgis.Critical,
        )
        QMessageBox.critical(
            None,
            tr("Error"),
            tr("Error saving map: {}").format(error_text),
        )
        return

    iface.messageBar().pushSuccess(
        tr("Success"),
        tr("Map '{}' has been saved successfully.").format(updated_styled_map.name),
    )
