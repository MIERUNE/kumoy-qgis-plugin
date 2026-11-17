"""kumoy:uploadvector — create a Kumoy vector from a vector layer.

Features are prepared and uploaded in one streaming pass: geometries are
reduced to 2D single parts in EPSG:4326 (the server's storage format), made
valid, and sent in batches as they are read. Nothing is copied into
intermediate layers, so memory stays flat for large layers.
"""

import json
import math
from dataclasses import dataclass
from itertools import chain
from typing import Any, Dict, Iterator, List, Optional, Set

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCsException,
    QgsFeatureRequest,
    QgsFields,
    QgsGeometry,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeatureSource,
    QgsProcessingFeedback,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterField,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QDate, QDateTime, QMetaType, QTime, QVariant

from .... import i18n
from ....kumoy import api, constants
from ....kumoy.api.qgis_vector import (
    MAX_ITEMS_PER_REQUEST,
    MAX_WKB_BASE64_LENGTH,
    encode_wkb,
)
from ....kumoy.tasks import Canceled
from ...base import KumoyUploadAlgorithm
from .normalize_field_name import MAX_FIELD_LENGTH, normalize_field_name, truncate_utf16

# PyQt5 exposes the type enum as QMetaType.Int as well, PyQt6 only as Type.Int
_TYPE = getattr(QMetaType, "Type", QMetaType)
_INTEGER_TYPES = (_TYPE.Int, _TYPE.UInt, _TYPE.LongLong, _TYPE.ULongLong)

_GEOMETRY_TYPES = {
    Qgis.GeometryType.Point: "POINT",
    Qgis.GeometryType.Line: "LINESTRING",
    Qgis.GeometryType.Polygon: "POLYGON",
}

# Body size budget of one add-features request (base64 WKB). A single
# geometry may reach MAX_WKB_BASE64_LENGTH; it is then sent alone.
_MAX_BATCH_WKB_LENGTH = 10_000_000


def _get_geometry_type(layer: QgsVectorLayer) -> Optional[str]:
    """Kumoy geometry type of the layer, or None when unsupported."""
    return _GEOMETRY_TYPES.get(layer.geometryType())


def _column_type(field_type: Any) -> str:
    if field_type == _TYPE.Bool:
        return "boolean"
    if field_type in _INTEGER_TYPES:
        return "integer"
    if field_type == _TYPE.Double:
        return "float"
    # Text, and anything without a Kumoy type (dates, JSON, lists) as text
    return "string"


@dataclass
class _Column:
    index: int  # in the source fields
    name: str  # on the server
    type: str  # integer | float | string | boolean


def _build_columns(
    fields: QgsFields,
    selected: Optional[Set[str]],
    feedback: QgsProcessingFeedback,
) -> List[_Column]:
    columns: List[_Column] = []
    for index, field in enumerate(fields):
        if selected and field.name() not in selected:
            continue
        name = normalize_field_name(field.name(), [c.name for c in columns])
        if not name:
            continue
        if name.startswith(constants.RESERVED_FIELD_NAME_PREFIX):
            feedback.pushWarning(
                i18n.tr("Skipping reserved field name '{}'").format(field.name())
            )
            continue
        if name != field.name():
            feedback.pushInfo(
                i18n.tr("Field '{}' normalized to '{}'").format(field.name(), name)
            )
        columns.append(_Column(index, name, _column_type(field.type())))
    return columns


def _to_json_value(value: Any, column_type: str) -> Any:
    """A JSON value the server accepts for a column of `column_type`."""
    if value is None or (isinstance(value, QVariant) and value.isNull()):
        return None
    if column_type == "float":
        value = float(value)
        # NaN and infinity are not valid JSON
        return value if math.isfinite(value) else None
    if column_type in ("integer", "boolean"):
        return value
    if isinstance(value, QDateTime):
        text = value.toString("yyyy-MM-ddTHH:mm:ss.zzz")
    elif isinstance(value, QDate):
        text = value.toString("yyyy-MM-dd")
    elif isinstance(value, QTime):
        text = value.toString("HH:mm:ss.zzz")
    elif isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value)
    return truncate_utf16(text, constants.MAX_CHARACTERS_STRING_FIELD)


def _prepare_geometry(
    geometry: QgsGeometry,
    geometry_type: Qgis.GeometryType,
    transform: Optional[QgsCoordinateTransform],
) -> List[QgsGeometry]:
    """The parts of a geometry as the server stores them, or [] to skip it."""
    if geometry.isNull() or geometry.isEmpty():
        return []
    geometry = QgsGeometry(geometry)
    # The server's columns are 2D
    part = geometry.get()
    part.dropZValue()
    part.dropMValue()
    if geometry.type() != geometry_type:
        return []
    box = geometry.boundingBox()
    # NaN coordinates make both comparisons false
    if not (box.xMinimum() <= box.xMaximum() and box.yMinimum() <= box.yMaximum()):
        return []
    if transform is not None:
        try:
            geometry.transform(transform)
        except QgsCsException:
            return []
    if geometry_type != Qgis.GeometryType.Point:
        # Repairing can split a polygon into several or degrade it to lines
        geometry = geometry.makeValid()
    return [
        p
        for p in geometry.asGeometryCollection()
        if p.type() == geometry_type and not p.isEmpty()
    ]


class UploadVectorAlgorithm(KumoyUploadAlgorithm):
    """Algorithm to upload vector layer to Kumoy backend"""

    GROUP_ID = "vector"
    VECTOR_NAME = "VECTOR_NAME"
    SELECTED_FIELDS = "SELECTED_FIELDS"
    OUTPUT = "OUTPUT"  # Hidden; kept so existing scripts' parameters stay valid

    def name(self) -> str:
        return "uploadvector"

    def displayName(self) -> str:
        return i18n.tr("Upload Vector Layer to Kumoy")

    def shortHelpString(self) -> str:
        return i18n.tr(
            "Upload a vector layer to the Kumoy cloud.\n\n"
            "The Input Vector Layer dropdown shows vector layers in your current map. "
            "If no map is open, it will be empty."
        ) + i18n.tr(
            "\n\nLimits:\n"
            "- If the name is left empty, the layer name is used, truncated to "
            "{} characters.\n"
            "- Field names longer than {} characters are truncated.\n"
            "- Text values longer than {} characters are truncated.\n"
            "- Fields whose names start with '{}' are skipped.\n"
            "- The geometry of each feature must be {:,} characters or less "
            "when encoded as Base64 WKB."
        ).format(
            constants.MAX_CHARACTERS_VECTOR_NAME,
            MAX_FIELD_LENGTH,
            constants.MAX_CHARACTERS_STRING_FIELD,
            constants.RESERVED_FIELD_NAME_PREFIX,
            MAX_WKB_BASE64_LENGTH,
        )

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_LAYER,
                i18n.tr("Input vector layer"),
                [Qgis.ProcessingSourceType.VectorAnyGeometry],
            )
        )
        self.add_project_parameters()
        self.addParameter(
            QgsProcessingParameterField(
                self.SELECTED_FIELDS,
                i18n.tr("Attributes to upload"),
                parentLayerParameterName=self.INPUT_LAYER,
                type=Qgis.ProcessingFieldParameterDataType.Any,
                optional=True,
                allowMultiple=True,
                defaultValue=[],
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.VECTOR_NAME,
                i18n.tr("{} (max {} characters)").format(
                    i18n.tr("Vector layer name"), constants.MAX_CHARACTERS_VECTOR_NAME
                ),
                defaultValue="",
                optional=True,
            )
        )
        sink = QgsProcessingParameterFeatureSink(
            self.OUTPUT,
            i18n.tr("Temporary output"),
            type=Qgis.ProcessingSourceType.VectorAnyGeometry,
            createByDefault=True,
            defaultValue="TEMPORARY_OUTPUT",
            optional=True,
        )
        sink.setFlags(sink.flags() | Qgis.ProcessingParameterFlag.Hidden)
        self.addParameter(sink)

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        layer = self.parameterAsVectorLayer(parameters, self.INPUT_LAYER, context)
        if layer is None:
            raise QgsProcessingException(i18n.tr("Invalid input layer"))
        if layer.dataProvider().name() == constants.DATA_PROVIDER_KEY:
            raise QgsProcessingException(
                i18n.tr("Cannot upload a layer that is already stored in server.")
            )
        geometry_type = _get_geometry_type(layer)
        if geometry_type is None:
            raise QgsProcessingException(i18n.tr("Unsupported geometry type"))
        # A snapshot that is safe to read in this (worker) thread
        source = self.parameterAsSource(parameters, self.INPUT_LAYER, context)
        if not source.sourceCrs().isValid():
            raise QgsProcessingException(
                i18n.tr(
                    "The input layer has an undefined or invalid coordinate "
                    "reference system. Please assign a valid CRS to the layer "
                    "before uploading."
                )
            )

        project_id = self._resolve_project_id(parameters, context)
        vector_name = self.parameter_as_name(
            parameters,
            self.VECTOR_NAME,
            context,
            layer.name(),
            constants.MAX_CHARACTERS_VECTOR_NAME,
        )
        selected = set(
            self.parameterAsFields(parameters, self.SELECTED_FIELDS, context)
        )
        if selected:
            feedback.pushInfo(
                i18n.tr("Using {} of {} attributes for upload").format(
                    len(selected), source.fields().count()
                )
            )
        columns = _build_columns(source.fields(), selected, feedback)

        plan = self.check_destination(project_id, "vector").planSettings
        feature_count = source.featureCount()
        if feature_count > plan.maxVectorFeatures:
            raise QgsProcessingException(
                i18n.tr(
                    "Cannot upload vector. The layer has {} features, "
                    "but your plan allows up to {} features per vector."
                ).format(feature_count, plan.maxVectorFeatures)
            )
        if len(columns) > plan.maxVectorAttributes:
            raise QgsProcessingException(
                i18n.tr(
                    "Cannot upload vector. The layer has {} attributes, "
                    "but your plan allows up to {} attributes per vector."
                ).format(len(columns), plan.maxVectorAttributes)
            )
        feedback.setProgress(5)

        progress = _Progress(feedback, feature_count)
        rows = _rows(source, layer.geometryType(), columns, context, progress)
        # Read up to the first valid feature before creating anything
        first = next(rows, None)
        if first is None:
            raise QgsProcessingException(
                i18n.tr("No features remain after filtering invalid geometries")
            )

        vector_id = api.vector.create_vector(project_id, vector_name, geometry_type)
        feedback.pushInfo(
            i18n.tr("Created vector layer '{}' with ID: {}").format(
                vector_name, vector_id
            )
        )
        try:
            if columns:
                api.qgis_vector.add_attributes(
                    vector_id, [{"name": c.name, "type": c.type} for c in columns]
                )
            for batch in _batches(chain([first], rows)):
                api.qgis_vector.add_features(vector_id, batch)
                progress.report_uploaded()
        except BaseException:
            # Do not leave a half-uploaded vector behind (also on cancel)
            try:
                api.vector.delete_vector(vector_id)
                feedback.pushInfo(
                    i18n.tr("Cleaned up incomplete vector layer due to upload failure")
                )
            except Exception as cleanup_error:
                feedback.reportError(
                    i18n.tr("Failed to clean up incomplete vector layer: {}").format(
                        str(cleanup_error)
                    )
                )
            raise

        if progress.skipped:
            feedback.pushInfo(
                i18n.tr(
                    "Removed {} features with missing or incompatible geometries."
                ).format(progress.skipped)
            )
        feedback.setProgress(100)
        return {"VECTOR_ID": vector_id}


def _rows(
    source: QgsProcessingFeatureSource,
    geometry_type: Qgis.GeometryType,
    columns: List[_Column],
    context: QgsProcessingContext,
    progress: "_Progress",
) -> Iterator[Dict[str, Any]]:
    """Yield add-features items, one per single-part geometry."""
    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    transform = None
    if source.sourceCrs() != wgs84:
        transform = QgsCoordinateTransform(
            source.sourceCrs(), wgs84, context.transformContext()
        )
    request = QgsFeatureRequest().setSubsetOfAttributes([c.index for c in columns])

    for feature in source.getFeatures(request):
        progress.read_one()
        parts = _prepare_geometry(feature.geometry(), geometry_type, transform)
        if not parts:
            progress.skipped += 1
            continue
        values = feature.attributes()
        properties = {c.name: _to_json_value(values[c.index], c.type) for c in columns}
        for part in parts:
            wkb = encode_wkb(part.asWkb())
            if len(wkb) > MAX_WKB_BASE64_LENGTH:
                raise QgsProcessingException(
                    i18n.tr(
                        "Cannot upload feature: geometry is too large. "
                        "Please simplify the geometry or split it into smaller "
                        "parts. Details: {}"
                    ).format(
                        i18n.tr(
                            "Feature geometry exceeds maximum WKB length ({} > {})"
                        ).format(f"{len(wkb):,}", f"{MAX_WKB_BASE64_LENGTH:,}")
                    )
                )
            yield {"kumoy_wkb": wkb, "properties": properties}


def _batches(rows: Iterator[Dict[str, Any]]) -> Iterator[List[Dict[str, Any]]]:
    """Group rows within the server's per-request limits."""
    batch: List[Dict[str, Any]] = []
    size = 0
    for row in rows:
        length = len(row["kumoy_wkb"])
        if batch and (
            len(batch) >= MAX_ITEMS_PER_REQUEST or size + length > _MAX_BATCH_WKB_LENGTH
        ):
            yield batch
            batch, size = [], 0
        batch.append(row)
        size += length
    if batch:
        yield batch


class _Progress:
    """Progress 5-100% by features read, and cancellation checks."""

    def __init__(self, feedback: QgsProcessingFeedback, total: int) -> None:
        self._feedback = feedback
        self._total = max(total, 1)
        self.read = 0
        self.skipped = 0

    def read_one(self) -> None:
        if self._feedback.isCanceled():
            raise Canceled()
        self.read += 1

    def report_uploaded(self) -> None:
        if self._feedback.isCanceled():
            raise Canceled()
        self._feedback.setProgress(5 + 95 * min(self.read / self._total, 1.0))
        self._feedback.pushInfo(
            i18n.tr("Upload complete: {} / {} features").format(self.read, self._total)
        )
