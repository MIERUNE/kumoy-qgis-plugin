from typing import Dict, List

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsDataProvider,
    QgsFeature,
    QgsFeatureIterator,
    QgsFeatureRequest,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsProviderRegistry,
    QgsRectangle,
    QgsVectorDataProvider,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant

from .. import api
from ..constants import (
    DATA_PROVIDER_DESCRIPTION,
    DATA_PROVIDER_KEY,
)
from . import local_cache
from .feature_iterator import QgishubFeatureIterator
from .feature_source import QgishubFeatureSource

ADD_MAX_FEATURE_COUNT = 1000
UPDATE_MAX_FEATURE_COUNT = 1000
DELETE_MAX_FEATURE_COUNT = 1000


def parse_uri(
    uri: str,
) -> tuple[str, str, str]:
    qgishubProviderMetadata = QgsProviderRegistry.instance().providerMetadata(
        DATA_PROVIDER_KEY
    )
    parsed_uri = qgishubProviderMetadata.decodeUri(uri)

    endpoint = parsed_uri.get("endpoint", "")
    project_id = parsed_uri.get("project_id", "")
    vector_id = parsed_uri.get("vector_id", "")

    # check parsing results
    if vector_id == "" or endpoint == "" or project_id == "":
        raise ValueError(
            "Invalid URI. 'endpoint', 'project_id' and 'vector_id' are required."
        )

    return (endpoint, project_id, vector_id)


class QgishubDataProvider(QgsVectorDataProvider):
    def __init__(
        self,
        uri="",
        providerOptions=QgsDataProvider.ProviderOptions(),
        flags=QgsDataProvider.ReadFlags(),
    ):
        super().__init__(uri)
        self._is_valid = False
        self._crs = QgsCoordinateReferenceSystem("EPSG:4326")

        self._extent = QgsRectangle()
        self.filter_where_clause = None

        # store arguments
        self._uri = uri
        self._provider_options = providerOptions
        self._flags = flags

        # Parse the URI
        _, project_id, vector_id = parse_uri(uri)
        self.qgishub_vector = api.project_vector.get_vector(project_id, vector_id)

        # local cache
        self._refresh_local_cache()
        self.cached_layer = local_cache.get_cached_layer(self.qgishub_vector.id)

        self._is_valid = True

        # Set native types based on PostgreSQL data type constraints
        self.setNativeTypes(
            [
                # INTEGER: 4-byte signed integer (-2147483648 to +2147483647)
                QgsVectorDataProvider.NativeType(
                    type=QVariant.Int,
                    typeDesc="Integer",
                    subType=QVariant.Int,
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
                    minLen=255,
                    maxLen=255,  # PostgreSQL allows up to 10485760 characters but allow up to 255 in our system
                    minPrec=0,  # Not applicable for varchar
                    maxPrec=0,  # Not applicable for varchar
                ),
            ]
        )

    def _refresh_local_cache(self):
        """Refresh local cache"""
        local_cache.sync_local_cache(
            self.qgishub_vector.id,
            self.raw_fields(),
            self.wkbType(),
        )

    @classmethod
    def providerKey(cls) -> str:
        return DATA_PROVIDER_KEY

    @classmethod
    def description(cls) -> str:
        return DATA_PROVIDER_DESCRIPTION

    @classmethod
    def createProvider(cls, uri, providerOptions, flags=QgsDataProvider.ReadFlags()):
        return QgishubDataProvider(uri, providerOptions, flags)

    def featureSource(self):
        return QgishubFeatureSource(self)

    def wkbType(self) -> QgsWkbTypes:
        if self.qgishub_vector.type == "POINT":
            return QgsWkbTypes.Point
        elif self.qgishub_vector.type == "LINESTRING":
            return QgsWkbTypes.LineString
        elif self.qgishub_vector.type == "POLYGON":
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
        return self.qgishub_vector.count

    def fields(self) -> QgsFields:
        fs = QgsFields()

        for column in self.qgishub_vector.columns:
            name = column["name"]
            suffix = name.split("_")[-1]  # e.g.) usercol_uuid_colname
            type_ = column["type"]

            len = 0
            if type_ == "string":
                data_type = QVariant.String
                len = 255
            elif type_ == "integer":
                data_type = QVariant.Int
            elif type_ == "float":
                data_type = QVariant.Double
            else:
                data_type = QVariant.Bool

            f = QgsField(suffix, data_type)
            if len > 0:
                f.setLength(len)
            fs.append(f)
        return fs

    def raw_fields(self) -> QgsFields:
        # ローカルキャッシュにはsuffixだけではなくfull column nameを保存する
        fields = self.fields()
        new_fields = QgsFields()
        for field in fields:
            # Convert suffix to full column name
            full_colname = self._get_suffix_to_full_column_name(field.name())
            new_field = QgsField(
                full_colname, field.type(), field.typeName(), field.length()
            )
            new_fields.append(new_field)
        return new_fields

    def extent(self) -> QgsRectangle:
        extent = self.qgishub_vector.extent  # [xmin, ymin, xmax, ymax]
        return QgsRectangle(extent[0], extent[1], extent[2], extent[3])

    def updateExtents(self) -> None:
        """Update extent"""
        return self._extent.setMinimal()

    def isValid(self) -> bool:
        return self._is_valid

    def geometryType(self) -> QgsWkbTypes:
        if self.qgishub_vector.type == "POINT":
            return QgsWkbTypes.Point
        elif self.qgishub_vector.type == "LINESTRING":
            return QgsWkbTypes.LineString
        elif self.qgishub_vector.type == "POLYGON":
            return QgsWkbTypes.Polygon
        else:
            return QgsWkbTypes.Unknown

    def crs(self) -> QgsCoordinateReferenceSystem:
        return self._crs

    def supportsSubsetString(self) -> bool:
        return False

    def capabilities(self) -> QgsVectorDataProvider.Capabilities:
        role = self.qgishub_vector.role

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
                | QgsVectorDataProvider.RenameAttributes
            )
        elif role == "MEMBER":
            return (
                QgsVectorDataProvider.SelectAtId
                | QgsVectorDataProvider.ReadLayerMetadata
            )

        return QgsVectorDataProvider.NoCapabilities

    def getFeatures(self, request=QgsFeatureRequest()) -> QgsFeature:
        return QgsFeatureIterator(
            QgishubFeatureIterator(QgishubFeatureSource(self), request)
        )

    def deleteFeatures(self, qgishub_ids: list[int]) -> bool:
        # Process in chunks of 1000 to avoid server limits
        for i in range(0, len(qgishub_ids), DELETE_MAX_FEATURE_COUNT):
            chunk = qgishub_ids[i : i + DELETE_MAX_FEATURE_COUNT]
            success = api.qgis_vector.delete_features(self.qgishub_vector.id, chunk)
            if not success:
                return False
        self._refresh_local_cache()
        return True

    def addFeatures(self, features: List[QgsFeature], flags=None):
        candidates: List[QgsFeature] = []

        for f in features:
            if not f.hasGeometry():
                # geometryがない地物は無視
                continue

            # geometryのwkbTypeが異なる場合は無視
            if f.hasGeometry() and (f.geometry().wkbType() != self.wkbType()):
                continue

            cur_feature = QgsFeature()
            cur_feature.setGeometry(f.geometry())
            cur_feature.setFields(self.raw_fields())

            # Set attributes
            for name in self.fields().names():
                # Convert suffix to full column name
                full_colname = self._get_suffix_to_full_column_name(name)
                cur_feature[full_colname] = f[name]

            candidates.append(cur_feature)

        if len(candidates) == 0:
            # 何もせず終了
            return True, []

        # 地物追加APIには地物数制限があるので、それを上回らないよう分割リクエストする
        for i in range(0, len(candidates), ADD_MAX_FEATURE_COUNT):
            sliced = candidates[i : i + ADD_MAX_FEATURE_COUNT]
            succeeded = api.qgis_vector.add_features(self.qgishub_vector.id, sliced)
            if not succeeded:
                return False, candidates[0:i]

        # reload
        self.qgishub_vector = api.project_vector.get_vector(
            self.qgishub_vector.projectId, self.qgishub_vector.id
        )

        self.clearMinMaxCache()
        self.updateExtents()
        self._refresh_local_cache()
        return True, candidates

    def changeAttributeValues(self, attr_map: Dict[str, dict]) -> bool:
        attribute_items = []

        for feature_id, raw_attr in attr_map.items():
            # raw_attr = {0: value, 1: value, ...}
            # preprocess as { field_name: value, ... }
            properties = {}
            for idx, value in raw_attr.items():
                field_name = self.fields().field(idx).name()
                # Convert suffix to full column name
                full_colname = self._get_suffix_to_full_column_name(field_name)
                properties[full_colname] = value

            attribute_items.append(
                {"qgishub_id": int(feature_id), "properties": properties}
            )

        if not attribute_items:
            return True

        # Process in chunks of 1000 to avoid server limits
        total_items = len(attribute_items)
        processed_items = 0

        for i in range(0, total_items, UPDATE_MAX_FEATURE_COUNT):
            chunk = attribute_items[i : i + UPDATE_MAX_FEATURE_COUNT]
            result = api.qgis_vector.change_attribute_values(
                vector_id=self.qgishub_vector.id, attribute_items=chunk
            )
            if not result:
                return False
            processed_items += len(chunk)

        # reload
        self.qgishub_vector = api.project_vector.get_vector(
            self.qgishub_vector.projectId, self.qgishub_vector.id
        )

        self.clearMinMaxCache()
        self._refresh_local_cache()
        return True

    def changeGeometryValues(self, geometry_map: Dict[str, QgsGeometry]) -> bool:
        geometry_items = [
            {"qgishub_id": int(feature_id), "geom": geometry.asWkb()}
            for feature_id, geometry in geometry_map.items()
        ]

        # Process in chunks of 1000 to avoid server limits
        for i in range(0, len(geometry_items), UPDATE_MAX_FEATURE_COUNT):
            chunk = geometry_items[i : i + UPDATE_MAX_FEATURE_COUNT]
            result = api.qgis_vector.change_geometry_values(
                vector_id=self.qgishub_vector.id, geometry_items=chunk
            )
            if not result:
                return False

        # reload
        self.qgishub_vector = api.project_vector.get_vector(
            self.qgishub_vector.projectId, self.qgishub_vector.id
        )
        self.updateExtents()
        self._refresh_local_cache()
        return True

    def renameAttributes(self, renamedAttributes: Dict[int, str]) -> bool:
        # Convert field index to field name mapping
        attribute_map = {}
        for idx, new_name in renamedAttributes.items():
            old_suffix = self.fields().field(idx).name()
            old_name = self._get_suffix_to_full_column_name(old_suffix)
            attribute_map[old_name] = new_name

        # Call the API to rename attributes
        success = api.qgis_vector.rename_attributes(
            vector_id=self.qgishub_vector.id, attribute_map=attribute_map
        )

        if success:
            # Update the vector information to reflect the changes
            self.qgishub_vector = api.project_vector.get_vector(
                self.qgishub_vector.projectId, self.qgishub_vector.id
            )
            self.clearMinMaxCache()
        self._refresh_local_cache()
        return success

    def addAttributes(self, attributes: List[QgsField]) -> bool:
        # Convert QgsField list to dictionary of name:type
        attr_dict = {}
        for field in attributes:
            # Map QGIS field types to our supported types
            field_type = "string"  # Default to string
            if field.type() == QVariant.Int:
                field_type = "integer"
            elif field.type() == QVariant.Double:
                field_type = "float"
            elif field.type() == QVariant.Bool:
                field_type = "boolean"

            column_name = field.name()
            attr_dict[column_name] = field_type

        # Call the API to add attributes
        success = api.qgis_vector.add_attributes(
            vector_id=self.qgishub_vector.id, attributes=attr_dict
        )
        if success:
            # Update the vector information to reflect the changes
            self.qgishub_vector = api.project_vector.get_vector(
                self.qgishub_vector.projectId, self.qgishub_vector.id
            )
            self.clearMinMaxCache()
        self._refresh_local_cache()
        return success

    def deleteAttributes(self, attribute_ids: List[int]) -> bool:
        # Convert field indices to field names
        attribute_names = [self.fields().field(idx).name() for idx in attribute_ids]

        full_colnames = []
        for name in attribute_names:
            # Convert suffix to full column name
            try:
                full_colname = self._get_suffix_to_full_column_name(name)
                full_colnames.append(full_colname)
            except ValueError as e:
                print(f"Error: {e}")
                return False

        # Call the API to delete attributes
        success = api.qgis_vector.delete_attributes(
            vector_id=self.qgishub_vector.id, attribute_names=full_colnames
        )

        if success:
            # Update the vector information to reflect the changes
            self.qgishub_vector = api.project_vector.get_vector(
                self.qgishub_vector.projectId, self.qgishub_vector.id
            )
            self.clearMinMaxCache()
        self._refresh_local_cache()
        return success

    def _get_suffix_to_full_column_name(self, suffix: str) -> str:
        """Convert suffix to full column name by searching in qgishub_vector.columns"""
        # e.g.) colname -> usercol_uuid_colname
        for column in self.qgishub_vector.columns:
            if column["name"].endswith(suffix):
                return column["name"]

        raise ValueError(f"Column with suffix '{suffix}' not found in vector columns.")
