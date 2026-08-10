import os
import tempfile
from typing import Any, Dict, List, Sequence

from qgis.core import (
    NULL,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QDate, QDateTime, QTime, QVariant


def _normalize_attribute(value: Any) -> Any:
    if value == NULL or (isinstance(value, QVariant) and value.isNull()):
        return None
    if isinstance(value, QDateTime):
        return value.toString("yyyy-MM-ddTHH:mm:ss.zzz")
    if isinstance(value, QDate):
        return value.toString("yyyy-MM-dd")
    if isinstance(value, QTime):
        return value.toString("HH:mm:ss.zzz")
    return value


def _normalized_properties(feature: QgsFeature) -> Dict[str, Any]:
    return {
        name: _normalize_attribute(feature[name])
        for name in feature.fields().names()
        if name != "kumoy_id"
    }


def _transfer_fields(source: QgsFields, geometry_only: bool) -> QgsFields:
    fields = QgsFields()
    if geometry_only:
        index = source.indexOf("kumoy_id")
        if index < 0:
            raise ValueError("Geometry update feature is missing kumoy_id")
        fields.append(QgsField(source.field(index)))
        return fields

    for field in source:
        if field.name() == "kumoy_id":
            continue
        if field.type() in (QVariant.DateTime, QVariant.Date, QVariant.Time):
            fields.append(QgsField(field.name(), QVariant.String))
        else:
            fields.append(QgsField(field))
    return fields


def _memory_layer(
    features: Sequence[QgsFeature], geometry_only: bool
) -> QgsVectorLayer:
    first = features[0]
    fields = _transfer_fields(first.fields(), geometry_only)
    geometry_types = {
        feature.geometry().wkbType()
        for feature in features
        if feature.hasGeometry() and not feature.geometry().isEmpty()
    }
    if not geometry_types:
        raise ValueError("At least one feature must have a geometry")
    if len(geometry_types) != 1:
        raise ValueError(
            "All features in a FlatGeobuf batch must share a geometry type"
        )
    wkb_type = geometry_types.pop()

    layer = QgsVectorLayer(
        f"{QgsWkbTypes.displayString(wkb_type)}?crs=EPSG:4326",
        "flatgeobuf-upload",
        "memory",
    )
    if not layer.isValid():
        raise RuntimeError("Failed to create FlatGeobuf memory layer")
    provider = layer.dataProvider()
    if not provider.addAttributes(list(fields)):
        raise RuntimeError("Failed to create FlatGeobuf transfer fields")
    layer.updateFields()

    prepared: List[QgsFeature] = []
    for source_feature in features:
        if source_feature.fields().names() != first.fields().names():
            raise ValueError("All features in a FlatGeobuf batch must share fields")

        feature = QgsFeature(layer.fields())
        if geometry_only:
            feature.setAttribute("kumoy_id", int(source_feature["kumoy_id"]))
        else:
            properties = _normalized_properties(source_feature)
            for name, value in properties.items():
                feature.setAttribute(name, value)
        if source_feature.hasGeometry():
            feature.setGeometry(source_feature.geometry())
        feature.setValid(True)
        prepared.append(feature)

    success, _ = provider.addFeatures(prepared)
    if not success:
        raise RuntimeError("Failed to populate FlatGeobuf memory layer")
    layer.updateExtents()
    return layer


def features_to_flatgeobuf(
    features: Sequence[QgsFeature], *, geometry_only: bool = False
) -> bytes:
    """Encode a homogeneous feature batch as a non-indexed FlatGeobuf file."""
    if not features:
        raise ValueError("FlatGeobuf batch must not be empty")

    layer = _memory_layer(features, geometry_only)
    fd, path = tempfile.mkstemp(suffix=".fgb")
    os.close(fd)

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "FlatGeobuf"
    options.fileEncoding = "UTF-8"
    options.layerOptions = ["SPATIAL_INDEX=NO"]
    options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile

    try:
        error, message, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            path,
            QgsProject.instance().transformContext(),
            options,
        )
        if error != QgsVectorFileWriter.NoError:
            raise RuntimeError(f"Failed to create FlatGeobuf upload: {message}")
        with open(path, "rb") as file:
            return file.read()
    finally:
        del layer
        if os.path.exists(path):
            os.unlink(path)
