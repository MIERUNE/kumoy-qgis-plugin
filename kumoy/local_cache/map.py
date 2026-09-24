import os
import shutil
import tempfile
from typing import Optional

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateTransform,
    QgsDataProvider,
    QgsMapSettings,
    QgsMessageLog,
    QgsProject,
    QgsProviderRegistry,
    QgsRectangle,
    QgsVectorLayer,
)
from qgis.PyQt.QtXml import QDomDocument

from ... import i18n
from ..constants import DATA_PROVIDER_KEY, LOG_CATEGORY, RASTER_DATA_PROVIDER_KEY
from ..sprite import pin_fixed_aspect_ratios
from .size import dir_total_size, files_total_size

# Flag to prevent double updates when handling the project saved event.
# When serialize_project() writes the QGIS project to disk, this guards against
# re-entrancy via the QgsProject.projectSaved signal.
is_updating = False

# Kumoy takes the initial view of a map from this <mapcanvas> element
MAP_CANVAS_NAME = "theMapCanvas"

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


def get_cache_size(map_id: str) -> int:
    """Return the map's cache size in bytes (0 when not cached).

    Uses the same matching rule as clear(): any file whose name contains map_id.
    """
    cache_dir = get_cache_dir()
    # Existence is the caller's concern: files_total_size expects paths that
    # exist. isfile also excludes directories that would fail getsize.
    matched = (os.path.join(cache_dir, f) for f in os.listdir(cache_dir) if map_id in f)
    return files_total_size(p for p in matched if os.path.isfile(p))


def get_total_cache_size() -> int:
    """Return the total size in bytes of all cached map files."""
    return dir_total_size(get_cache_dir())


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

    # Subdirectories too: clear_all must cover everything dir_total_size counts.
    for entry in list(os.scandir(cache_dir)):
        try:
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path)
            else:
                os.unlink(entry.path)
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
                f"Unexpected error for {entry.path}: {e}",
                LOG_CATEGORY,
                Qgis.Critical,
            )
            success = False  # Flag unsucceed

    return success


def refresh_kumoy_layer_extents(project: QgsProject) -> None:
    """Re-read the extent of every Kumoy vector layer from its provider.

    QgsVectorLayer caches the provider extent for the layer's lifetime, and
    write() omits <extent> entirely when it is null. A Kumoy layer returns null
    while the server has no extent yet (empty/just-uploaded vector, failed
    metadata fetch), so a layer unlucky in when it was first asked would be
    saved without an extent forever after.

    Vector layers only: other providers don't have this bug and rescanning them
    can be expensive; QgsRasterLayer has no updateExtents(), and a Kumoy raster
    is null only when its download failed, which no retry here can fix.
    """
    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue
        provider = layer.dataProvider()
        if provider is None or provider.name() != DATA_PROVIDER_KEY:
            continue
        # Preferred: recomputes from the provider and folds in uncommitted edits.
        layer.updateExtents()
        if not layer.extent().isNull():  # also forces the recompute now
            continue
        # updateExtents() is a no-op while featureCount() is 0, so write the
        # server extent directly for layers that cannot produce features.
        provider_extent = provider.extent()
        if not provider_extent.isNull():
            layer.setExtent(provider_extent)


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
    refresh_kumoy_layer_extents(project)

    prev_name = project.fileName()
    prev_dirty = project.isDirty()
    is_updating = True
    try:
        return _write_to_string(project)
    finally:
        is_updating = False
        project.setFileName(prev_name)
        project.setDirty(prev_dirty)


def read_project_file(path: str) -> QgsProject:
    """Read a .qgs / .qgz into a standalone project, leaving Kumoy layers unresolved.

    Resolving a Kumoy layer starts its data provider, which syncs the local
    cache behind a GUI progress dialog; saving the map only needs its symbols.
    """
    project = QgsProject()
    _stand_in_for_map_canvas(project)
    if not project.read(path, Qgis.ProjectReadFlag.DontResolveLayers):
        raise RuntimeError(
            i18n.tr("Failed to read the QGIS project file: {}").format(project.error())
        )

    for layer in project.mapLayers().values():
        if layer.providerType() in (DATA_PROVIDER_KEY, RASTER_DATA_PROVIDER_KEY):
            continue
        # An unresolved layer is written back with its datasource as read, so a
        # relative path would still point from the original file's directory
        decoded = QgsProviderRegistry.instance().decodeUri(
            layer.providerType(), layer.source()
        )
        if not decoded.get("path"):
            continue
        options = QgsDataProvider.ProviderOptions()
        options.transformContext = project.transformContext()
        layer.setDataSource(layer.source(), layer.name(), layer.providerType(), options)
    return project


def _stand_in_for_map_canvas(project: QgsProject) -> None:
    """Keep <mapcanvas> in a project written without the GUI.

    Only QgsMapCanvas reads and writes that element, so a standalone project
    drops it and the map would open at 0,0. A project built by a script has
    none to begin with; its default view extent stands in for the canvas.
    """
    settings = QgsMapSettings()

    def read(doc: QDomDocument) -> None:
        nodes = doc.elementsByTagName("mapcanvas")
        for i in range(nodes.count()):
            if nodes.item(i).toElement().attribute("name") == MAP_CANVAS_NAME:
                settings.readXml(nodes.item(i))
                return

    def write(doc: QDomDocument) -> None:
        if settings.extent().isEmpty():
            settings.setDestinationCrs(project.crs())
            settings.setExtent(_initial_extent(project))
        node = doc.createElement("mapcanvas")
        node.setAttribute("name", MAP_CANVAS_NAME)
        settings.writeXml(node, doc)
        doc.documentElement().appendChild(node)

    project.readProject.connect(read)
    project.writeProject.connect(write)


def _initial_extent(project: QgsProject) -> QgsRectangle:
    """Return the extent to open the project at, in the project CRS."""
    view = project.viewSettings().defaultViewExtent()
    if view.isEmpty():
        view = project.viewSettings().fullExtent()
    if view.crs() == project.crs() or not view.crs().isValid():
        return QgsRectangle(view)
    return QgsCoordinateTransform(
        view.crs(), project.crs(), project
    ).transformBoundingBox(view)


def serialize_detached_project(project: QgsProject) -> str:
    """Serialize a project read by read_project_file() as serialize_project() does."""
    pin_fixed_aspect_ratios(project)
    return _write_to_string(project)


def _write_to_string(project: QgsProject) -> str:
    # Force .qgs (plain XML) — .qgz would be compressed.
    fd, tmp_path = tempfile.mkstemp(suffix=".qgs", dir=get_cache_dir())
    os.close(fd)
    try:
        project.write(tmp_path)
        with open(tmp_path, "r", encoding="utf-8") as f:
            return f.read()
    finally:
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
