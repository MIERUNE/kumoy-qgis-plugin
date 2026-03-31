from __future__ import annotations

import hashlib
import io
import os
import shutil
import zipfile

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsBlockingNetworkRequest,
    QgsMessageLog,
    QgsProject,
)
from qgis.PyQt.QtCore import QCoreApplication, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.utils import iface

from ... import settings_manager
from ...pyqt_version import Q_MESSAGEBOX_STD_BUTTON
from ...ui.layers.convert_vector import (
    convert_local_layers,
)
from .. import api, map_assets
from ..constants import LOG_CATEGORY

# Flag to prevent double updates when handling project saved event
is_updating = False


def tr(message: str, context: str = "@default") -> str:
    return QCoreApplication.translate(context, message)


def show_map_save_result(
    map_name: str,
    conversion_errors: list[tuple[str, str]],
) -> None:
    """Show success or warning message after map save operation.

    Args:
        map_name: Name of the map
        conversion_errors: List of (layer_name, error_message) tuples
    """
    if conversion_errors:
        error_details = "\n".join(
            [f"• {layer_name}\n{error}\n" for layer_name, error in conversion_errors]
        )
        # Limit error details length
        msg_max_length = 1000
        if len(error_details) > msg_max_length:
            error_details = error_details[:msg_max_length] + "..."

        report_msg = tr(
            "Map '{}' has been saved successfully.\n\n"
            "Warning: {} layers could not be converted:\n\n{}"
        ).format(map_name, len(conversion_errors), error_details)

        QMessageBox.warning(None, tr("Map Saved with Warnings"), report_msg)
    else:
        # No conversion errors means also no local layers to convert
        report_msg = tr("Map '{}' has been saved successfully.").format(map_name)
        iface.messageBar().pushSuccess(tr("Success"), report_msg)


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
    map_dir = os.path.join(cache_dir, map_id)
    os.makedirs(map_dir, exist_ok=True)
    return os.path.join(map_dir, "map.qgs")


def get_assets_dir(map_id: str) -> str:
    """Return the directory where asset files are extracted for a specific map."""
    cache_dir = _get_cache_dir()
    assets_dir = os.path.join(cache_dir, map_id, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    return assets_dir


def download_and_extract_assets(map_id: str, download_url: str) -> None:
    """Download asset ZIP from presigned URL and extract to cache directory.

    Args:
        map_id: Map ID
        download_url: Presigned download URL for the ZIP file
    """
    req = QNetworkRequest(QUrl(download_url))
    blocking_request = QgsBlockingNetworkRequest()
    err = blocking_request.get(req, forceRefresh=True)

    if err != QgsBlockingNetworkRequest.NoError:
        error_message = blocking_request.errorMessage()
        raise Exception(f"Failed to download assets: {error_message}")

    zip_data = bytes(blocking_request.reply().content().data())

    # Extract to assets directory
    assets_dir = get_assets_dir(map_id)
    with zipfile.ZipFile(io.BytesIO(zip_data), "r") as zf:
        zf.extractall(assets_dir)

    QgsMessageLog.logMessage(
        f"Assets extracted to {assets_dir}",
        LOG_CATEGORY,
        Qgis.Info,
    )


def clear(map_id: str) -> bool:
    """Clear cache for a specific map.
    Returns True if all files were deleted successfully, False otherwise.
    """
    cache_dir = _get_cache_dir()
    map_dir = os.path.join(cache_dir, map_id)
    if not os.path.isdir(map_dir):
        return True
    try:
        shutil.rmtree(map_dir)
        return True
    except PermissionError as e:
        QgsMessageLog.logMessage(
            f"Ignored file access error for {map_dir}: {e}",
            LOG_CATEGORY,
            Qgis.Info,
        )
        return False
    except Exception as e:
        QgsMessageLog.logMessage(
            f"Unexpected error for {map_dir}: {e}",
            LOG_CATEGORY,
            Qgis.Critical,
        )
        return False


def clear_all() -> bool:
    """Clear all cached map files. Returns True if all files were deleted successfully."""

    cache_dir = _get_cache_dir()
    success = True

    # Remove all files and directories in cache directory
    for filename in os.listdir(cache_dir):
        file_path = os.path.join(cache_dir, filename)
        try:
            if os.path.isdir(file_path):
                shutil.rmtree(file_path)
            else:
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


def upload_assets_and_update_map(
    styled_map_detail: api.styledmap.KumoyStyledMapDetail,
) -> api.styledmap.UpdateStyledMapResponse:
    """Collect symbol assets, rewrite paths, and upload to server.

    Args:
        styled_map_detail: StyledMap detail object

    Returns:
        Updated StyledMap detail object
    """
    project = QgsProject.instance()
    collected = map_assets.collect_assets(project)

    # create assets.zip / sprite
    map_assets.copy_files_and_rewrite_paths(
        project, collected.files, get_assets_dir(styled_map_detail.id)
    )
    zip_bytes = map_assets.build_asset_zip(collected.files)
    sprite_json, sprite_png = map_assets.generate_sprites(collected.sprites)

    # Compute hash
    h = hashlib.sha256()
    h.update(zip_bytes)
    h.update(sprite_json)
    h.update(sprite_png)
    assets_hash = h.hexdigest()[:16]

    if assets_hash == styled_map_detail.assetsHash:
        QgsMessageLog.logMessage(
            "Assets are unchanged. Skipping upload.",
            LOG_CATEGORY,
            Qgis.Info,
        )

    server_url = api.config.get_api_config().SERVER_URL

    # Get presigned URLs for all assets at once
    upload_urls = api.styledmap_assets.get_assets_upload_urls(
        styled_map_detail.id,
        len(zip_bytes),
        len(sprite_json),
        len(sprite_png),
    )

    # Upload ZIP
    map_assets.upload_to_presigned_url(
        server_url,
        upload_urls.zip.fields,
        upload_urls.zip.filename,
        zip_bytes,
        "application/zip",
    )

    if collected.sprites:
        # Upload sprites
        map_assets.upload_to_presigned_url(
            server_url,
            upload_urls.json.fields,
            upload_urls.json.filename,
            sprite_json,
            "application/json",
        )
        map_assets.upload_to_presigned_url(
            server_url,
            upload_urls.png.fields,
            upload_urls.png.filename,
            sprite_png,
            "image/png",
        )

    qgsproject_str = write_qgsfile(styled_map_detail.id)

    updated_styled_map = api.styledmap.update_styled_map(
        styled_map_detail.id,
        api.styledmap.UpdateStyledMapOptions(
            qgisproject=qgsproject_str,
            assetsHash=assets_hash,
        ),
    )

    return updated_styled_map


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

    # Get and validate map belongs to current project
    try:
        styled_map_detail = api.styledmap.get_styled_map(styled_map_id)
        settings = settings_manager.get_settings()

        if settings.selected_project_id != styled_map_detail.projectId:
            QMessageBox.critical(
                None,
                tr("Wrong Project"),
                tr(
                    "This map belongs to a different Kumoy project. "
                    "Please switch to the correct project."
                ),
            )
            return
    except Exception as e:
        error_text = api.error.format_api_error(e)
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

    # Convert local layers to Kumoy layers if any
    cancelled, conversion_errors = convert_local_layers(styled_map_detail.projectId)
    if cancelled:
        return

    try:
        # Collect and upload assets (rewrites symbol layer paths)
        updated_styled_map = upload_assets_and_update_map(styled_map_detail)
    except Exception as e:
        error_text = api.error.format_api_error(e)
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

    # reopen qgs to refresh project with new styled map data
    QgsProject.instance().clear()
    QgsProject.instance().read(get_filepath(styled_map_id))

    # Show success message with conversion errors summary if any
    show_map_save_result(updated_styled_map.name, conversion_errors)
