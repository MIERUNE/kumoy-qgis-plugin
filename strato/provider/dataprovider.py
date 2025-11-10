from typing import Dict, List, Optional

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsDataProvider,
    QgsFeature,
    QgsFeatureIterator,
    QgsFeatureRequest,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsMessageLog,
    QgsProviderRegistry,
    QgsRectangle,
    QgsVectorDataProvider,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import (
    QCoreApplication,
    QEventLoop,
    Qt,
    QThread,
    QVariant,
    pyqtSignal,
)
from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog

from .. import api, constants
from . import local_cache
from .feature_iterator import StratoFeatureIterator
from .feature_source import StratoFeatureSource

ADD_MAX_FEATURE_COUNT = 1000
UPDATE_MAX_FEATURE_COUNT = 1000
DELETE_MAX_FEATURE_COUNT = 1000


class SyncWorker(QThread):
    """Worker thread for sync_local_cache operation"""

    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, vector_id, fields, wkb_type):
        super().__init__()
        self.vector_id = vector_id
        self.fields = fields
        self.wkb_type = wkb_type

    def run(self):
        try:
            local_cache.sync_local_cache(
                self.vector_id,
                self.fields,
                self.wkb_type,
            )
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))


def parse_uri(
    uri: str,
) -> tuple[str, str]:
    stratoProviderMetadata = QgsProviderRegistry.instance().providerMetadata(
        constants.DATA_PROVIDER_KEY
    )
    parsed_uri = stratoProviderMetadata.decodeUri(uri)

    project_id = parsed_uri.get("project_id", "")
    vector_id = parsed_uri.get("vector_id", "")
    vector_name = parsed_uri.get("vector_name", "")

    # check parsing results
    if vector_id == "" or project_id == "":
        raise ValueError(
            "Invalid URI. 'endpoint', 'project_id' and 'vector_id' are required."
        )

    return (project_id, vector_id, vector_name)


class StratoDataProvider(QgsVectorDataProvider):
    def __init__(
        self,
        uri="",
        providerOptions=QgsDataProvider.ProviderOptions(),
        flags=QgsDataProvider.ReadFlags(),
    ):
        super().__init__(uri)
        self._is_valid = False
        self._crs = QgsCoordinateReferenceSystem("EPSG:4326")

        # store arguments
        self._uri = uri
        self._provider_options = providerOptions
        self._flags = flags

        # Parse the URI
        self.project_id, self.vector_id, self.vector_name = parse_uri(uri)

        # local cache
        self.strato_vector: Optional[api.project_vector.StratoVectorDetail] = None
        self._reload_vector()

        if self.strato_vector is None:
            return

        self.cached_layer = local_cache.get_cached_layer(self.strato_vector.id)

        self._is_valid = True

        # Set native types based on PostgreSQL data type constraints
        self.setNativeTypes(
            [
                # INTEGER: 4-byte signed integer (-2147483648 to +2147483647)
                QgsVectorDataProvider.NativeType(
                    type=QVariant.LongLong,
                    typeDesc="Integer",
                    subType=QVariant.LongLong,
                    typeName="INTEGER",
                    minLen=0,  # Not applicable for integers
                    maxLen=0,  # Not applicable for integers
                    minPrec=0,  # Not applicable for integers
                    maxPrec=0,  # Not applicable for integers
                ),
                # DOUBLE PRECISION: 8-byte floating-point number, variable precision
                QgsVectorDataProvider.NativeType(
                    type=QVariant.Double,
                    typeDesc="Double Precision",
                    subType=QVariant.Double,
                    typeName="DOUBLE PRECISION",
                    minLen=0,  # Not applicable for floats
                    maxLen=0,  # Not applicable for floats
                    minPrec=0,  # Variable precision
                    maxPrec=15,  # PostgreSQL double precision has about 15 decimal digits precision
                ),
                # BOOLEAN: true/false
                QgsVectorDataProvider.NativeType(
                    type=QVariant.Bool,
                    typeDesc="Boolean",
                    subType=QVariant.Bool,
                    typeName="BOOLEAN",
                    minLen=0,  # Not applicable for boolean
                    maxLen=0,  # Not applicable for boolean
                    minPrec=0,  # Not applicable for boolean
                    maxPrec=0,  # Not applicable for boolean
                ),
                # VARCHAR: variable length character string with limit
                QgsVectorDataProvider.NativeType(
                    type=QVariant.String,
                    typeDesc="Varchar",
                    subType=QVariant.String,
                    typeName="VARCHAR",
                    minLen=constants.MAX_CHARACTERS_STRING_FIELD,  # Minimum length for our system
                    maxLen=constants.MAX_CHARACTERS_STRING_FIELD,  # Maximum length for our system
                    minPrec=0,  # Not applicable for varchar
                    maxPrec=0,  # Not applicable for varchar
                ),
            ]
        )

    def tr(self, message):
        """Get the translation for a string using Qt translation API"""
        return QCoreApplication.translate("StratoDataProvider", message)

    def _reload_vector(self):
        """Refresh local cache"""
        try:
            self.strato_vector = api.project_vector.get_vector(
                self.project_id, self.vector_id
            )
        except Exception as e:
            if e.args[0] == "Not Found":
                QMessageBox.information(
                    None,
                    self.tr("Vector not found"),
                    self.tr("The following vector does not exist: {}").format(
                        self.vector_name
                    ),
                )
                return
            else:
                raise e

        # Show loading dialog for sync_local_cache operation
        progress = QProgressDialog(
            self.tr("Syncing: {}").format(self.strato_vector.name),
            self.tr("Cancel"),
            0,
            0,
        )
        progress.setWindowTitle(self.tr("Data Sync"))
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setMinimumDuration(0)  # Show immediately
        progress.setValue(100)  # Set to middle to show indeterminate progress
        progress.setAutoClose(False)  # Don't auto-close
        progress.setAutoReset(False)  # Don't auto-reset
        progress.show()

        # Create event loop for non-blocking operation
        loop = QEventLoop()
        sync_cancelled = False
        sync_error = None

        # Create and configure worker thread
        sync_worker = SyncWorker(self.strato_vector.id, self.fields(), self.wkbType())

        def on_sync_finished():
            loop.quit()

        def on_sync_error(error_message):
            nonlocal sync_error
            sync_error = error_message
            loop.quit()

        def on_progress_cancelled():
            nonlocal sync_cancelled
            sync_cancelled = True
            if sync_worker.isRunning():
                sync_worker.terminate()
                sync_worker.wait()
            loop.quit()

        # Connect signals
        sync_worker.finished.connect(on_sync_finished)
        sync_worker.error.connect(on_sync_error)
        progress.canceled.connect(on_progress_cancelled)

        # Start sync in background and wait for completion
        sync_worker.start()
        loop.exec_()  # This keeps UI responsive while waiting

        # Clean up
        progress.accept()
        sync_worker.deleteLater()

        # Handle results
        if sync_cancelled:
            # キャンセル時はレイヤーを追加したくないので例外を投げる
            raise Exception(self.tr("Sync cancelled by user"))
        elif sync_error:
            # Log error but continue with existing cached data
            QgsMessageLog.logMessage(
                self.tr("Sync error: {}").format(sync_error), "STRATO", Qgis.Warning
            )

        self.cached_layer = local_cache.get_cached_layer(self.strato_vector.id)
        self.clearMinMaxCache()

    @classmethod
    def providerKey(cls) -> str:
        return constants.DATA_PROVIDER_KEY

    @classmethod
    def description(cls) -> str:
        return constants.DATA_PROVIDER_DESCRIPTION

    @classmethod
    def createProvider(cls, uri, providerOptions, flags=QgsDataProvider.ReadFlags()):
        return StratoDataProvider(uri, providerOptions, flags)

    def featureSource(self):
        return StratoFeatureSource(self)

    def wkbType(self) -> QgsWkbTypes:
        if self.strato_vector is None:
            return QgsWkbTypes.Unknown
        if self.strato_vector.type == "POINT":
            return QgsWkbTypes.Point
        elif self.strato_vector.type == "LINESTRING":
            return QgsWkbTypes.LineString
        elif self.strato_vector.type == "POLYGON":
            return QgsWkbTypes.Polygon
        else:
            return QgsWkbTypes.Unknown

    def name(self) -> str:
        """Return the name of provider

        :return: Name of provider
        :rtype: str
        """
        return self.providerKey()

    def featureCount(self) -> int:
        """Return the feature count, respecting subset string if set."""
        if self.strato_vector is None:
            return 0
        return self.strato_vector.count

    def fields(self) -> QgsFields:
        fs = QgsFields()
        fs.append(QgsField("strato_id", QVariant.LongLong))
        if self.strato_vector is None:
            return fs
        for column in self.strato_vector.columns:
            k = column["name"]
            v = column["type"]

            len = 0
            if v == "string":
                data_type = QVariant.String
                len = constants.MAX_CHARACTERS_STRING_FIELD
            elif v == "integer":
                data_type = QVariant.LongLong
            elif v == "float":
                data_type = QVariant.Double
            else:
                data_type = QVariant.Bool

            f = QgsField(k, data_type)
            if len > 0:
                f.setLength(len)
            fs.append(f)

        return fs

    def extent(self) -> QgsRectangle:
        if self.strato_vector is None:
            return QgsRectangle()
        return QgsRectangle(*self.strato_vector.extent)

    def isValid(self) -> bool:
        return self._is_valid

    def geometryType(self) -> QgsWkbTypes:
        if self.strato_vector is None:
            return QgsWkbTypes.Unknown
        if self.strato_vector.type == "POINT":
            return QgsWkbTypes.Point
        elif self.strato_vector.type == "LINESTRING":
            return QgsWkbTypes.LineString
        elif self.strato_vector.type == "POLYGON":
            return QgsWkbTypes.Polygon
        else:
            return QgsWkbTypes.Unknown

    def crs(self) -> QgsCoordinateReferenceSystem:
        return self._crs

    def supportsSubsetString(self) -> bool:
        return False

    def capabilities(self) -> QgsVectorDataProvider.Capabilities:
        if self.strato_vector is None:
            return QgsVectorDataProvider.NoCapabilities
        role = self.strato_vector.role

        if role == "OWNER" or role == "ADMIN":
            return (
                QgsVectorDataProvider.SelectAtId
                | QgsVectorDataProvider.AddFeatures
                | QgsVectorDataProvider.DeleteFeatures
                | QgsVectorDataProvider.ChangeFeatures
                | QgsVectorDataProvider.ChangeAttributeValues
                | QgsVectorDataProvider.ChangeGeometries
                | QgsVectorDataProvider.AddAttributes
                | QgsVectorDataProvider.DeleteAttributes
            )
        elif role == "MEMBER":
            return (
                QgsVectorDataProvider.SelectAtId
                | QgsVectorDataProvider.ReadLayerMetadata
            )

        return QgsVectorDataProvider.NoCapabilities

    def getFeatures(self, request=QgsFeatureRequest()) -> QgsFeature:
        return QgsFeatureIterator(
            StratoFeatureIterator(StratoFeatureSource(self), request)
        )

    def deleteFeatures(self, strato_ids: list[int]) -> bool:
        # Process in chunks of 1000 to avoid server limits
        for i in range(0, len(strato_ids), DELETE_MAX_FEATURE_COUNT):
            chunk = strato_ids[i : i + DELETE_MAX_FEATURE_COUNT]
            try:
                api.qgis_vector.delete_features(self.strato_vector.id, chunk)
            except Exception:
                return False
        self._reload_vector()
        return True

    def addFeatures(self, features: List[QgsFeature], flags=None):
        candidates: list[QgsFeature] = list(
            filter(
                lambda f: f.hasGeometry()
                and (f.geometry().wkbType() == self.wkbType()),
                features,
            )
        )

        if len(candidates) == 0:
            # 何もせず終了
            return True, []

        # 地物追加APIには地物数制限があるので、それを上回らないよう分割リクエストする
        for i in range(0, len(features), ADD_MAX_FEATURE_COUNT):
            sliced = candidates[i : i + ADD_MAX_FEATURE_COUNT]
            try:
                api.qgis_vector.add_features(self.strato_vector.id, sliced)
            except Exception:
                return False, candidates[0:i]

        # reload
        self._reload_vector()
        return True, candidates

    def changeAttributeValues(self, attr_map: Dict[str, dict]) -> bool:
        attribute_items = []

        for feature_id, raw_attr in attr_map.items():
            # raw_attr = {0: value, 1: value, ...}
            # preprocess as { field_name: value, ... }
            properties = {}
            for idx, value in raw_attr.items():
                field_name = self.fields().field(idx).name()
                if field_name == "strato_id":
                    # Skip strato_id as it is not a valid field for update
                    continue
                properties[field_name] = value

            attribute_items.append(
                {"strato_id": int(feature_id), "properties": properties}
            )

        if not attribute_items:
            return True

        # Process in chunks of 1000 to avoid server limits
        total_items = len(attribute_items)
        for i in range(0, total_items, UPDATE_MAX_FEATURE_COUNT):
            chunk = attribute_items[i : i + UPDATE_MAX_FEATURE_COUNT]
            try:
                api.qgis_vector.change_attribute_values(
                    vector_id=self.strato_vector.id, attribute_items=chunk
                )
            except Exception:
                return False

        self._reload_vector()
        return True

    def changeGeometryValues(self, geometry_map: Dict[str, QgsGeometry]) -> bool:
        geometry_items = [
            {"strato_id": int(feature_id), "geom": geometry.asWkb()}
            for feature_id, geometry in geometry_map.items()
        ]

        # Process in chunks of 1000 to avoid server limits
        for i in range(0, len(geometry_items), UPDATE_MAX_FEATURE_COUNT):
            chunk = geometry_items[i : i + UPDATE_MAX_FEATURE_COUNT]
            try:
                api.qgis_vector.change_geometry_values(
                    vector_id=self.strato_vector.id, geometry_items=chunk
                )
            except Exception:
                return False

        self._reload_vector()
        return True

    def addAttributes(self, attributes: List[QgsField]) -> bool:
        # Convert QgsField list to dictionary of name:type
        attr_dict = {}
        for field in attributes:
            # Map QGIS field types to our supported types
            field_type = "string"  # Default to string
            if field.type() == QVariant.LongLong:
                field_type = "integer"
            elif field.type() == QVariant.Double:
                field_type = "float"
            elif field.type() == QVariant.Bool:
                field_type = "boolean"

            column_name = field.name()
            attr_dict[column_name] = field_type

        # Call the API to add attributes
        try:
            api.qgis_vector.add_attributes(
                vector_id=self.strato_vector.id, attributes=attr_dict
            )
        except Exception:
            return False

        self._reload_vector()
        return True

    def deleteAttributes(self, attribute_ids: List[int]) -> bool:
        # Convert field indices to field names
        attribute_names = [self.fields().field(idx).name() for idx in attribute_ids]

        # Call the API to delete attributes
        try:
            api.qgis_vector.delete_attributes(
                vector_id=self.strato_vector.id, attribute_names=attribute_names
            )
        except Exception:
            return False

        self._reload_vector()
        return True
