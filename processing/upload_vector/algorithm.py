from typing import Any, Dict, Optional, Set

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsMessageLog,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterField,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.utils import iface

import processing

from ...settings_manager import get_settings
from ...strato import api, constants
from ...strato.api.error import format_api_error
from ...strato.get_token import get_token
from .normalize_field_name import normalize_field_name


def _get_geometry_type(layer: QgsVectorLayer) -> Optional[str]:
    """Determine geometry type and check for multipart"""
    wkb_type = layer.wkbType()
    if wkb_type in [
        QgsWkbTypes.Point,
        QgsWkbTypes.PointZ,
        QgsWkbTypes.MultiPoint,
        QgsWkbTypes.MultiPointZ,
    ]:
        vector_type = "POINT"
    elif wkb_type in [
        QgsWkbTypes.LineString,
        QgsWkbTypes.LineStringZ,
        QgsWkbTypes.MultiLineString,
        QgsWkbTypes.MultiLineStringZ,
    ]:
        vector_type = "LINESTRING"
    elif wkb_type in [
        QgsWkbTypes.Polygon,
        QgsWkbTypes.PolygonZ,
        QgsWkbTypes.MultiPolygon,
        QgsWkbTypes.MultiPolygonZ,
    ]:
        vector_type = "POLYGON"
    else:
        vector_type = None

    return vector_type


def _create_attribute_dict(valid_fields_layer: QgsVectorLayer) -> Dict[str, str]:
    """Convert QgsField list to dictionary of name:type"""
    attr_dict = {}
    for field in valid_fields_layer.fields():
        # Map QGIS field types to our supported types
        field_type = "string"  # Default to string
        if (
            field.type() == QVariant.Int or field.type() == QVariant.LongLong
        ):  # LongLong is for 64-bit integers
            field_type = "integer"
        elif field.type() == QVariant.Double:
            field_type = "float"
        elif field.type() == QVariant.Bool:
            field_type = "boolean"

        column_name = field.name()
        attr_dict[column_name] = field_type

    return attr_dict


class UploadVectorAlgorithm(QgsProcessingAlgorithm):
    """Algorithm to upload vector layer to STRATO backend"""

    INPUT_LAYER: str = "INPUT"
    STRATO_PROJECT: str = "PROJECT"
    VECTOR_NAME: str = "VECTOR_NAME"
    SELECTED_FIELDS: str = "SELECTED_FIELDS"
    OUTPUT: str = "OUTPUT"  # Hidden output for internal processing

    project_map: Dict[str, str] = {}

    def tr(self, string: str) -> str:
        """Translate string"""
        return QCoreApplication.translate("UploadVectorAlgorithm", string)

    def createInstance(self) -> "UploadVectorAlgorithm":
        """Create new instance of algorithm"""
        return UploadVectorAlgorithm()

    def name(self) -> str:
        """Algorithm name"""
        return "uploadvector"

    def displayName(self) -> str:
        """Algorithm display name"""
        return self.tr("Upload Vector Layer to STRATO")

    def group(self):
        return None

    def groupId(self):
        return None

    def shortHelpString(self) -> str:
        """Short help string"""
        return self.tr(
            "Upload a vector layer to the STRATO cloud.\n\n"
            "The Input Vector Layer dropdown shows vector layers in your current map. "
            "If no map is open, it will be empty."
        )

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        """Initialize algorithm parameters"""
        project_options = []
        self.project_map = {}

        # Input vector layer
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_LAYER,
                self.tr("Input vector layer"),
                [QgsProcessing.TypeVectorAnyGeometry],
            )
        )

        try:
            if get_token() is None:
                # 未ログイン
                return

            # Get all organizations first
            organizations = api.organization.get_organizations()
            project_options = []
            project_ids = []

            # Get projects for each organization
            for org in organizations:
                projects = api.project.get_projects_by_organization(org.id)
                for project in projects:
                    project_options.append(f"{org.name} / {project.name}")
                    project_ids.append(project.id)

        except Exception as e:
            msg = self.tr("Error Initializing Processing: {}").format(
                format_api_error(e)
            )
            QgsMessageLog.logMessage(msg, constants.LOG_CATEGORY, Qgis.Critical)
            iface.messageBar().pushMessage(
                constants.PLUGIN_NAME, msg, level=Qgis.Critical, duration=10
            )
            return

        self.project_map = dict(zip(project_options, project_ids))
        default_project_index = 0
        selected_project_id = get_settings().selected_project_id
        if selected_project_id and self.project_map:
            # Find the index for the selected project ID
            for idx, (_, pid) in enumerate(self.project_map.items()):
                if pid == selected_project_id:
                    default_project_index = idx
                    break

        # Project selection
        self.addParameter(
            QgsProcessingParameterEnum(
                self.STRATO_PROJECT,
                self.tr("Destination project"),
                options=project_options,
                allowMultiple=False,
                optional=False,
                defaultValue=default_project_index,
            )
        )

        # Field selection
        self.addParameter(
            QgsProcessingParameterField(
                self.SELECTED_FIELDS,
                self.tr("Attributes to upload"),
                parentLayerParameterName=self.INPUT_LAYER,
                type=QgsProcessingParameterField.Any,
                optional=True,
                allowMultiple=True,
                defaultValue=[],
            )
        )

        # Vector name
        self.addParameter(
            QgsProcessingParameterString(
                self.VECTOR_NAME,
                self.tr("Vector layer name"),
                defaultValue="",
                optional=True,
            )
        )

        # Hidden output parameter for internal processing
        param = QgsProcessingParameterFeatureSink(
            self.OUTPUT,
            self.tr("Temporary output"),
            type=QgsProcessing.TypeVectorAnyGeometry,
            createByDefault=True,
            defaultValue="TEMPORARY_OUTPUT",
            optional=True,
        )
        param.setFlags(param.flags() | QgsProcessingParameterFeatureSink.FlagHidden)
        self.addParameter(param)

    def _get_project_info_and_validate(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        layer: QgsVectorLayer,
    ):
        """Get project information and validate limits"""
        # Get project ID
        project_index = self.parameterAsEnum(parameters, self.STRATO_PROJECT, context)
        project_options = list(self.project_map.keys())
        project_id = self.project_map[project_options[project_index]]

        # Get vector name
        vector_name = self.parameterAsString(parameters, self.VECTOR_NAME, context)
        if not vector_name:
            vector_name = layer.name()[:32]  # 最大32文字

        # Get project and plan limits
        project = api.project.get_project(project_id)
        organization = api.organization.get_organization(project.organizationId)
        plan_limits = api.plan.get_plan_limits(organization.subscriptionPlan)

        # Check vector count limit
        current_vectors = api.project_vector.get_vectors(project_id)
        upload_vector_count = len(current_vectors) + 1
        if upload_vector_count > plan_limits.maxVectors:
            raise QgsProcessingException(
                self.tr(
                    "Cannot upload vector. Your plan allows up to {} vectors per project, "
                    "but you already have {} vectors."
                ).format(plan_limits.maxVectors, upload_vector_count)
            )

        return project_id, vector_name, plan_limits

    def processAlgorithm(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        """Process the algorithm"""
        vector = None

        try:
            # Get input layer
            # 入力レイヤーのproviderチェック
            layer = self.parameterAsVectorLayer(parameters, self.INPUT_LAYER, context)
            if layer is None:
                raise QgsProcessingException(self.tr("Invalid input layer"))
            if layer.dataProvider().name() == constants.DATA_PROVIDER_KEY:
                raise QgsProcessingException(
                    self.tr("Cannot upload a layer that is already stored in server.")
                )

            # Get project information and validate
            project_id, vector_name, plan_limits = self._get_project_info_and_validate(
                parameters, context, layer
            )

            # クリーニング前のレイヤーで地物数チェック
            layer_feature_count = layer.featureCount()
            if layer_feature_count > plan_limits.maxVectorFeatures:
                raise QgsProcessingException(
                    self.tr(
                        "Cannot upload vector. The layer has {} features, "
                        "but your plan allows up to {} features per vector."
                    ).format(layer_feature_count, plan_limits.maxVectorFeatures)
                )

            # Determine geometry type
            geometry_type = _get_geometry_type(layer)
            if geometry_type is None:
                raise QgsProcessingException(self.tr("Unsupported geometry type"))

            # Process layer: convert to singlepart and reproject in one step
            selected_fields = set(
                self.parameterAsFields(parameters, self.SELECTED_FIELDS, context)
            )

            fields_count = layer.fields().count()

            if selected_fields:
                feedback.pushInfo(
                    self.tr("Using {} of {} attributes for upload").format(
                        len(selected_fields), fields_count
                    )
                )
                fields_count = len(selected_fields)

            if fields_count > plan_limits.maxVectorAttributes:
                raise QgsProcessingException(
                    self.tr(
                        "Cannot upload vector. The layer has {} attributes, "
                        "but your plan allows up to {} attributes per vector."
                    ).format(fields_count, plan_limits.maxVectorAttributes)
                )

            field_mapping = self._build_field_mapping(
                layer,
                feedback,
                selected_fields if selected_fields else None,
            )

            processed_layer = self._process_layer_geometry(
                layer,
                field_mapping,
                context,
                feedback,
            )

            # クリーニング後にも再度地物数と属性数をチェック（multipart→singlepartで増える可能性があるため）
            proc_feature_count = processed_layer.featureCount()
            if proc_feature_count > plan_limits.maxVectorFeatures:
                raise QgsProcessingException(
                    self.tr(
                        "Cannot upload vector. The layer has {} features, "
                        "but your plan allows up to {} features per vector."
                    ).format(proc_feature_count, plan_limits.maxVectorFeatures)
                )

            # Create attribute dictionary
            attr_dict = _create_attribute_dict(processed_layer)

            # Create vector
            options = api.project_vector.AddVectorOptions(
                name=vector_name,
                type=geometry_type,
            )
            vector = api.project_vector.add_vector(project_id, options)
            feedback.pushInfo(
                self.tr("Created vector layer '{}' with ID: {}").format(
                    vector_name, vector.id
                )
            )

            # Add attributes to vector
            api.qgis_vector.add_attributes(vector_id=vector.id, attributes=attr_dict)
            feedback.pushInfo(
                self.tr("Added attributes to vector layer '{}': {}").format(
                    vector_name, ", ".join(attr_dict.keys())
                )
            )

            # Upload features
            self._upload_features(vector.id, processed_layer, feedback)

            return {"VECTOR_ID": vector.id}

        except Exception as e:
            # If vector was created but upload failed, delete it
            if vector is not None:
                try:
                    api.project_vector.delete_vector(vector.id)
                    feedback.pushInfo(
                        self.tr(
                            "Cleaned up incomplete vector layer due to upload failure"
                        )
                    )
                except Exception as cleanup_error:
                    feedback.reportError(
                        self.tr(
                            "Failed to clean up incomplete vector layer: {}"
                        ).format(str(cleanup_error))
                    )

            # Re-raise the original exception
            raise e

    def _process_layer_geometry(
        self,
        layer: QgsVectorLayer,
        field_mapping: Dict[str, Dict[str, Any]],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> QgsVectorLayer:
        """Run processing-based pipeline to prepare geometries"""

        source_crs = layer.crs()
        if not source_crs.isValid():
            raise QgsProcessingException(
                self.tr(
                    "The input layer has an undefined or invalid coordinate reference system. "
                    "Please assign a valid CRS to the layer before uploading."
                )
            )

        if not field_mapping:
            raise QgsProcessingException(
                self.tr(
                    "No attributes available for upload. Select at least one attribute."
                )
            )

        # Step 1: attribute refactor
        mapping_list = [
            field_mapping[field.name()]
            for field in layer.fields()
            if field.name() in field_mapping
        ]

        if not mapping_list:
            raise QgsProcessingException(
                self.tr("Could not create the field mapping using the selected fields.")
            )

        geometry_filter_expr = self._build_geometry_filter_expression(layer)
        feedback.pushInfo(
            self.tr("Filtering features using expression: {}").format(
                geometry_filter_expr
            )
        )
        filtered_layer = self._run_child_algorithm(
            "native:extractbyexpression",
            {
                "INPUT": layer,
                "EXPRESSION": geometry_filter_expr,
                "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT,
            },
            context,
            feedback,
        )

        filtered_count = filtered_layer.featureCount()
        if filtered_count < layer.featureCount():
            feedback.pushInfo(
                self.tr(
                    "Removed {} features with missing or incompatible geometries."
                ).format(layer.featureCount() - filtered_count)
            )

        if filtered_layer.featureCount() == 0:
            raise QgsProcessingException(
                self.tr("No features remain after filtering invalid geometries")
            )

        current_layer = filtered_layer

        # Step 2: drop Z (keep M values untouched)
        if QgsWkbTypes.hasZ(current_layer.wkbType()):
            feedback.pushInfo(self.tr("Dropping Z coordinates"))
            current_layer = self._run_child_algorithm(
                "native:dropmzvalues",
                {
                    "INPUT": current_layer,
                    "DROP_M_VALUES": False,
                    "DROP_Z_VALUES": True,
                    "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT,
                },
                context,
                feedback,
            )

        # Step 3: repair geometries prior to other operations
        feedback.pushInfo(self.tr("Repairing geometries..."))
        current_layer = self._run_child_algorithm(
            "native:fixgeometries",
            {
                "INPUT": current_layer,
                "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT,
            },
            context,
            feedback,
        )

        # Step 4: convert to singlepart if needed
        if QgsWkbTypes.isMultiType(current_layer.wkbType()):
            feedback.pushInfo(self.tr("Converting multipart to singlepart"))
            current_layer = self._run_child_algorithm(
                "native:multiparttosingleparts",
                {
                    "INPUT": current_layer,
                    "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT,
                },
                context,
                feedback,
            )

        # Step 5: transform to EPSG:4326 when needed
        if current_layer.crs().authid() != "EPSG:4326":
            feedback.pushInfo(
                self.tr("Reprojecting from {} to EPSG:4326").format(
                    current_layer.crs().authid()
                )
            )
            current_layer = self._run_child_algorithm(
                "native:reprojectlayer",
                {
                    "INPUT": current_layer,
                    "TARGET_CRS": QgsCoordinateReferenceSystem("EPSG:4326"),
                    "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT,
                },
                context,
                feedback,
            )

        feedback.pushInfo(self.tr("Refactoring attributes..."))
        current_layer = self._run_child_algorithm(
            "native:refactorfields",
            {
                "INPUT": current_layer,
                "FIELDS_MAPPING": mapping_list,
                "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT,
            },
            context,
            feedback,
        )

        return current_layer

    def _build_field_mapping(
        self,
        layer: QgsVectorLayer,
        feedback: QgsProcessingFeedback,
        allowed_fields: Optional[Set[str]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Create field mapping for refactor step"""

        mapping: Dict[str, Dict[str, Any]] = {}
        for field in layer.fields():
            if allowed_fields is not None and field.name() not in allowed_fields:
                continue

            if field.name().startswith(constants.RESERVED_FIELD_NAME_PREFIX):
                feedback.pushWarning(
                    self.tr("Skipping reserved field name '{}'").format(field.name())
                )
                continue

            if field.type() not in [
                QVariant.String,
                QVariant.Int,
                QVariant.LongLong,  # LongLong is for 64-bit integers
                QVariant.Double,
                QVariant.Bool,
            ]:
                feedback.pushInfo(
                    self.tr(
                        "Unsupported field type for field '{}'. "
                        "Only string, integer, float, and boolean fields are supported."
                    ).format(field.name())
                )
                continue

            current_names = [
                m["name"] for m in mapping.values()
            ]  # ここまでに正規化済みのフィールド名
            normalized_name = normalize_field_name(field.name(), current_names)
            if not normalized_name:
                continue

            expression = f'"{field.name()}"'
            length = field.length()
            if field.type() == QVariant.String:
                # STRING型フィールドは255文字に制限
                expression = f"coalesce(left(\"{field.name()}\", {constants.MAX_CHARACTERS_STRING_FIELD}), '')"
                length = constants.MAX_CHARACTERS_STRING_FIELD

            mapping[field.name()] = {
                "expression": expression,
                "length": length,
                "name": normalized_name,
                "precision": field.precision(),
                "type": field.type(),
            }

            feedback.pushInfo(
                self.tr("Field '{}' normalized to '{}'").format(
                    field.name(), normalized_name
                )
            )

        return mapping

    def _build_geometry_filter_expression(self, layer: QgsVectorLayer) -> str:
        geom_type = QgsWkbTypes.geometryType(layer.wkbType())
        if geom_type == QgsWkbTypes.PointGeometry:
            allowed_type = "Point"
        elif geom_type == QgsWkbTypes.LineGeometry:
            allowed_type = "Line"
        elif geom_type == QgsWkbTypes.PolygonGeometry:
            allowed_type = "Polygon"
        else:
            raise QgsProcessingException(
                self.tr("Filtering failed due to an unsupported geometry type.")
            )

        return f"NOT is_empty_or_null($geometry) AND geometry_type($geometry) = '{allowed_type}'"

    def _run_child_algorithm(
        self,
        algorithm_id: str,
        params: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> QgsVectorLayer:
        """Execute child processing algorithm and return its layer output"""

        result = processing.run(
            algorithm_id,
            params,
            context=context,
            feedback=feedback,
            is_child_algorithm=True,
        )

        output = result.get("OUTPUT")
        if isinstance(output, QgsVectorLayer):
            return output

        if isinstance(output, str):
            layer = context.getMapLayer(output)
            if layer is not None:
                return layer

            layer = QgsVectorLayer(output, algorithm_id, "ogr")
            if layer.isValid():
                return layer

        raise QgsProcessingException(
            self.tr("The '{}' processing step failed to create a valid layer.").format(
                algorithm_id
            )
        )

    def _upload_features(
        self,
        vector_id: str,
        valid_fields_layer: QgsVectorLayer,
        feedback: QgsProcessingFeedback,
    ) -> None:
        """Upload features to STRATO in batches"""
        cur_features = []
        accumulated_features = 0
        batch_size = 1000

        for f in valid_fields_layer.getFeatures():
            if len(cur_features) >= batch_size:
                api.qgis_vector.add_features(vector_id, cur_features)

                accumulated_features += len(cur_features)
                feedback.pushInfo(
                    self.tr("Upload complete: {} / {} features").format(
                        accumulated_features, valid_fields_layer.featureCount()
                    )
                )
                feedback.setProgress(
                    50
                    + int(
                        (accumulated_features / valid_fields_layer.featureCount()) * 50
                    )
                )
                cur_features = []
            cur_features.append(f)

        # Upload remaining features
        if cur_features:
            api.qgis_vector.add_features(vector_id, cur_features)
            accumulated_features += len(cur_features)
            feedback.pushInfo(
                self.tr("Upload complete: {} / {} features").format(
                    accumulated_features, valid_fields_layer.featureCount()
                )
            )
