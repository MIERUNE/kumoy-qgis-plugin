import os

from typing import List, Optional

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsMessageLog,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)

from ..constants import LOG_CATEGORY
from .settings import delete_last_updated


def _get_cache_dir() -> str:
    """Return the directory where cache files are stored.
    data_type: subdirectory name maps or vectors"""
    setting_dir = QgsApplication.qgisSettingsDirPath()
    cache_dir = os.path.join(setting_dir, "kumoygis", "local_cache", "vectors")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _cache_file_path(vector_id: str) -> str:
    return os.path.join(_get_cache_dir(), f"{vector_id}.gpkg")


def _create_empty_cache(
    cache_file: str, fields: QgsFields, geometry_type: QgsWkbTypes.GeometryType
):
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.layerOptions = ["FID=kumoy_id"]
    options.driverName = "GPKG"
    options.fileEncoding = "UTF-8"

    writer = QgsVectorFileWriter.create(
        cache_file,
        fields,
        geometry_type,
        QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsProject.instance().transformContext(),
        options,
    )

    if writer.hasError() != QgsVectorFileWriter.NoError:
        QgsMessageLog.logMessage(
            f"Error creating cache file {cache_file}: {writer.errorMessage()}",
            LOG_CATEGORY,
            Qgis.Critical,
        )
        raise Exception(
            f"Error creating cache file {cache_file}: {writer.errorMessage()}"
        )

    del writer


def _ensure_layer_schema(layer: QgsVectorLayer, fields: QgsFields):
    """Ensure the cache layer matches the expected schema."""
    provider = layer.dataProvider()
    layer_fields = layer.fields()

    # Add missing fields
    missing = []
    for field in fields:
        if layer_fields.indexOf(field.name()) == -1:
            new_field = QgsField(field)
            missing.append(new_field)

    if missing:
        provider.addAttributes(missing)

    # Remove extra fields (except kumoy_id)
    to_remove = []
    for field in layer_fields:
        if field.name() == "kumoy_id":
            continue
        if fields.indexOf(field.name()) == -1:
            to_remove.append(layer_fields.indexOf(field.name()))

    if to_remove:
        provider.deleteAttributes(to_remove)

    if missing or to_remove:
        layer.updateFields()


def ensure_layer(
    vector_id: str,
    fields: QgsFields,
    geometry_type: QgsWkbTypes.GeometryType,
) -> QgsVectorLayer:
    """Ensure the cache layer exists and matches the latest schema."""
    cache_file = _cache_file_path(vector_id)

    if not os.path.exists(cache_file):
        _create_empty_cache(cache_file, fields, geometry_type)

    layer = QgsVectorLayer(cache_file, "cache", "ogr")

    if not layer.isValid():
        QgsMessageLog.logMessage(
            f"Cache layer {vector_id} is not valid.", LOG_CATEGORY, Qgis.Critical
        )
        raise Exception(f"Cache layer {vector_id} is not valid")

    _ensure_layer_schema(layer, fields)
    return layer


def append_features(
    vector_id: str,
    layer: QgsVectorLayer,
    fields: QgsFields,
    remote_features: List[dict],
) -> List[QgsFeature]:
    """Append freshly fetched remote features to the cache layer."""
    if layer is None or not layer.isValid():
        raise Exception(
            f"Cannot append features because cache layer {vector_id} is invalid"
        )

    provider = layer.dataProvider()
    qgs_fields = layer.fields()
    created: List[QgsFeature] = []

    for remote_feature in remote_features:
        qgs_feature = QgsFeature(qgs_fields)
        qgs_feature.setFields(qgs_fields, True)
        qgs_feature.setId(int(remote_feature["kumoy_id"]))

        geometry = QgsGeometry()
        geometry.fromWkb(remote_feature["kumoy_wkb"])
        qgs_feature.setGeometry(geometry)

        props = remote_feature.get("properties", {})
        qgs_feature.setAttribute("kumoy_id", int(remote_feature["kumoy_id"]))

        for name in fields.names():
            if name == "kumoy_id":
                continue
            qgs_feature.setAttribute(name, props.get(name))

        qgs_feature.setValid(True)
        created.append(qgs_feature)

    if not created:
        return []

    success, added = provider.addFeatures(created)
    if not success:
        print(f"FAILED added: {added}")

        QgsMessageLog.logMessage(
            f"Failed to append features to cache for {vector_id}.",
            LOG_CATEGORY,
            Qgis.Critical,
        )

    layer.updateExtents()
    return added


def get_layer(vector_id: str) -> Optional[QgsVectorLayer]:
    cache_file = _cache_file_path(vector_id)
    if not os.path.exists(cache_file):
        return None

    layer = QgsVectorLayer(cache_file, "cache", "ogr")
    if layer.isValid():
        return layer

    QgsMessageLog.logMessage(
        f"Cache layer {vector_id} is not valid.", LOG_CATEGORY, Qgis.Info
    )
    return None


def max_cached_kumoy_id(layer: QgsVectorLayer) -> Optional[int]:
    if layer is None or not layer.isValid():
        return None

    idx = layer.fields().indexOf("kumoy_id")
    if idx == -1:
        return None

    value = layer.maximumValue(idx)
    if value in (None, ""):
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def clear_all() -> bool:
    """Clear all cached GPKG files. Returns True if all files were deleted successfully."""

    cache_dir = _get_cache_dir()
    success = True

    # Remove all files in cache directory
    for filename in os.listdir(cache_dir):
        file_path = os.path.join(cache_dir, filename)
        try:
            os.unlink(file_path)
            if filename.endswith(".gpkg"):
                project_id = filename.split(".gpkg")[0]
                delete_last_updated(project_id)
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


def clear(vector_id: str) -> bool:
    """Clear cache for a specific vector.
    Returns True if all files were deleted successfully, False otherwise.
    """
    cache_dir = _get_cache_dir()
    cache_file = os.path.join(cache_dir, f"{vector_id}.gpkg")
    gpkg_shm_file = f"{cache_file}-shm"
    gpkg_wal_file = f"{cache_file}-wal"
    gpkg_journal_file = f"{cache_file}-journal"

    files_to_remove = [cache_file, gpkg_shm_file, gpkg_wal_file, gpkg_journal_file]
    success = True

    # Remove cache file if it exists
    for f in files_to_remove:
        if os.path.exists(f):
            try:
                os.unlink(f)
            except PermissionError as e:
                QgsMessageLog.logMessage(
                    f"Ignored file access error for {f}: {e}", LOG_CATEGORY, Qgis.Info
                )
                success = False  # Flag unsucceed deletion
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Unexpected error for {f}: {e}",
                    LOG_CATEGORY,
                    Qgis.Critical,
                )
    # Delete last updated timestamp
    delete_last_updated(vector_id)

    return success
