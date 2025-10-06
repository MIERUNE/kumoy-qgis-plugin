from typing import Any, Dict, Optional, Set, Tuple, cast

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsGeometry,
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

import processing

from ...settings_manager import get_settings
from ...strato import api, constants
from ...strato.get_token import get_token
from .normalize_field_name import normalize_field_name


def force_2d_geometry(geometry: QgsGeometry) -> QgsGeometry:
    """Return geometry without Z values, cloning when needed"""
    if not geometry or geometry.isEmpty():
        return geometry

    if not QgsWkbTypes.hasZ(geometry.wkbType()):
        return geometry

    abstract_geometry = geometry.constGet()
    if abstract_geometry is None:
        return geometry

    cloned_geometry = abstract_geometry.clone()
    cloned_geometry.dropZValue()
    return QgsGeometry(cloned_geometry)


def rename_field_with_refactor(
    layer: QgsVectorLayer, field_mapping: Dict[str, str]
) -> QgsVectorLayer:
    """リファクタリングツールを使用してフィールド名を変更"""

    # フィールドマッピングの作成
    # field_mapping = {
    #     '元のカラム名1': '新しいカラム名1',
    #     '元のカラム名2': '新しいカラム名2'
    # }

    # マッピング設定を作成
    fields_mapping = []
    for field in layer.fields():
        field_name = field.name()

        new_name = field_mapping.get(field_name)
        if new_name is None:
            continue

        mapping = {
            "expression": f'"{field_name}"',
            "length": field.length(),
            "name": new_name,
            "precision": field.precision(),
            "type": field.type(),
        }
        fields_mapping.append(mapping)

    # リファクタリング実行
    params = {"INPUT": layer, "FIELDS_MAPPING": fields_mapping, "OUTPUT": "memory:"}

    result = processing.run("native:refactorfields", params)
    return result["OUTPUT"]


def _is_geometry_type_consistent(geometry: QgsGeometry, expected_type: str) -> bool:
    """check if geometry type matches expected type"""
    if not geometry:
        return False

    actual_type = QgsWkbTypes.geometryType(geometry.wkbType())
    return actual_type == expected_type


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
        if field.type() == QVariant.Int:
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
            "Upload a vector layer to the Strato backend.\n\n"
            "User operation steps:\n"
            "1. Select the vector layer you want to upload from the dropdown\n"
            "2. Choose the destination project from Organization/Project list\n"
            "3. (Optional) Enter a custom name for the vector layer, or leave empty to use the original layer name\n"
            "4. Click 'Run' to start the upload process\n\n"
            "The algorithm will:\n"
            "- Automatically normalize field names (lowercase, remove special characters)\n"
            "- Automatically check and fix invalid geometries before processing\n"
            "- Automatically convert multipart geometries to single parts\n"
            "- Drop Z coordinates if present\n"
            "- Reproject to EPSG:4326 if other CRS set\n"
            "- Create a new vector layer in the selected project\n"
            "- Let you choose which attributes are uploaded\n"
            "Note: You must be logged in to Strato before using this tool."
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
                [QgsProcessing.TypeVector],
            )
        )

        # Get available projects
        token = get_token()
        if token:
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

            # Determine geometry type
            geometry_type = _get_geometry_type(layer)
            if geometry_type is None:
                raise QgsProcessingException(self.tr("Unsupported geometry type"))

            # Process layer: convert to singlepart and reproject in one step
            selected_fields = set(
                self.parameterAsFields(parameters, self.SELECTED_FIELDS, context)
            )

            if selected_fields:
                feedback.pushInfo(
                    self.tr("Using {} of {} attributes for upload").format(
                        len(selected_fields), layer.fields().count()
                    )
                )

            processed_layer, original_crs = self._process_layer_geometry(
                layer,
                QgsWkbTypes.isMultiType(layer.wkbType()),
                QgsWkbTypes.hasZ(layer.wkbType()),
                parameters,
                context,
                feedback,
            )

            # Check feature count limit
            proc_feature_count = processed_layer.featureCount()
            if proc_feature_count > plan_limits.maxVectorFeatures:
                raise QgsProcessingException(
                    self.tr(
                        "Cannot upload vector. The layer has {} features, "
                        "but your plan allows up to {} features per vector."
                    ).format(proc_feature_count, plan_limits.maxVectorFeatures)
                )

            # Check attribute count limit after normalization
            proc_layer_field_count = processed_layer.fields().count()
            if proc_layer_field_count > plan_limits.maxVectorAttributes:
                raise QgsProcessingException(
                    self.tr(
                        "Cannot upload vector. The layer has {} attributes, "
                        "but your plan allows up to {} attributes per vector."
                    ).format(proc_layer_field_count, plan_limits.maxVectorAttributes)
                )

            # Normalize field names
            valid_fields_layer = self._prepare_field_mappings(
                processed_layer, feedback, selected_fields if selected_fields else None
            )

            if valid_fields_layer.fields().isEmpty():
                raise QgsProcessingException(
                    self.tr(
                        "No attributes available for upload. Select at least one attribute."
                    )
                )

            # Create attribute dictionary
            attr_dict = _create_attribute_dict(valid_fields_layer)

            # Create vector and add attributes
            vector = self._create_vector_and_attributes(
                project_id, vector_name, geometry_type, attr_dict, feedback
            )

            # Upload features
            self._upload_features(vector.id, valid_fields_layer, feedback)

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
        is_multipart: bool,
        has_z: bool,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Tuple[QgsVectorLayer, QgsCoordinateReferenceSystem]:
        """Process layer geometry: convert to singlepart and reproject to EPSG:4326 in one step"""
        source_crs = layer.crs()
        target_crs = QgsCoordinateReferenceSystem("EPSG:4326")

        # Check if CRS is valid
        if not source_crs.isValid():
            raise QgsProcessingException(
                self.tr(
                    "The input layer has an undefined or invalid coordinate reference system. "
                    "Please assign a valid CRS to the layer before uploading."
                )
            )

        # Check if processing is needed (always check for invalid geometries)
        needs_multipart_conversion = is_multipart
        needs_reprojection = source_crs.authid() != "EPSG:4326"

        # Log processing steps
        processing_steps = [self.tr("Checking and fixing invalid geometries")]
        if needs_multipart_conversion:
            processing_steps.append(self.tr("Converting multipart to singlepart"))
        if needs_reprojection:
            processing_steps.append(
                self.tr("Reprojecting from {} to EPSG:4326").format(source_crs.authid())
            )
        if has_z:
            processing_steps.append(self.tr("Dropping Z coordinates"))

        feedback.pushInfo(self.tr("Processing layer: ") + ", ".join(processing_steps))

        # Get the target geometry type (always single part, force XY when needed)
        target_wkb_type = QgsWkbTypes.singleType(layer.wkbType())
        if has_z:
            target_wkb_type = QgsWkbTypes.flatType(target_wkb_type)
        expected_geom_type = QgsWkbTypes.geometryType(target_wkb_type)

        # Create sink with target CRS and geometry type
        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            layer.fields(),
            target_wkb_type,
            target_crs,
        )

        if sink is None:
            raise QgsProcessingException(
                self.tr("Could not create temporary sink for processing")
            )

        # Create coordinate transform if needed
        transform = None
        if needs_reprojection:
            transform = QgsCoordinateTransform(
                source_crs, target_crs, context.transformContext()
            )

        # Process features
        total_features = layer.featureCount()
        features_processed = 0
        fixed_geometries = 0
        invalid_geometries = 0
        wrong_geometry_type = 0

        for current, feature in enumerate(layer.getFeatures()):
            feature = cast(QgsFeature, feature)
            if feedback.isCanceled():
                break

            if not feature.hasGeometry():
                continue

            geom = feature.geometry()

            # Check and fix invalid geometry
            if not geom.isGeosValid():
                fixed_geom = geom.makeValid()
                if fixed_geom.isGeosValid():
                    geom = fixed_geom
                    fixed_geometries += 1
                else:
                    invalid_geometries += 1
                    continue  # Skip features that can't be fixed

            # Handle multipart geometries
            if needs_multipart_conversion and geom.isMultipart():
                # Convert multipart to singlepart
                single_geometry_parts = geom.asGeometryCollection()
                for single_geometry_part in single_geometry_parts:
                    # Check and fix invalid geometry part
                    if not single_geometry_part.isGeosValid():
                        fixed_part = single_geometry_part.makeValid()
                        if fixed_part.isGeosValid():
                            single_geometry_part = fixed_part
                            fixed_geometries += 1
                        else:
                            invalid_geometries += 1
                            continue  # Skip unfixable parts

                    # Check geometry type consistency
                    if not _is_geometry_type_consistent(
                        single_geometry_part, expected_geom_type
                    ):
                        wrong_geometry_type += 1
                        continue  # Skip parts with wrong geometry type

                    base_geometry = single_geometry_part.constGet()
                    if base_geometry is None:
                        invalid_geometries += 1
                        continue

                    part_geom = QgsGeometry(base_geometry.clone())

                    if has_z:
                        part_geom = force_2d_geometry(part_geom)

                    if transform:
                        part_geom.transform(transform)

                    # Create new feature for each part
                    new_feature = QgsFeature(feature)
                    new_feature.setGeometry(part_geom)

                    # Add to sink
                    if not sink.addFeature(new_feature, QgsFeatureSink.FastInsert):
                        raise QgsProcessingException(
                            self.tr("Error processing feature")
                        )
                    features_processed += 1
            else:
                # Check geometry type consistency
                if not _is_geometry_type_consistent(geom, expected_geom_type):
                    wrong_geometry_type += 1
                    continue  # Skip features with wrong geometry type

                # Single part geometry
                new_feature = QgsFeature(feature)

                base_geometry = geom.constGet()
                if base_geometry is None:
                    invalid_geometries += 1
                    continue

                geom_copy = QgsGeometry(base_geometry.clone())

                if has_z:
                    geom_copy = force_2d_geometry(geom_copy)

                if transform:
                    geom_copy.transform(transform)

                new_feature.setGeometry(geom_copy)

                # Add to sink
                if not sink.addFeature(new_feature, QgsFeatureSink.FastInsert):
                    raise QgsProcessingException(self.tr("Error processing feature"))
                features_processed += 1

            # Update progress (0-50% for geometry processing)
            if total_features > 0:
                progress = int((current + 1) / total_features * 50)
                feedback.setProgress(progress)

        feedback.pushInfo(
            self.tr("Geometry processing completed: {} features processed").format(
                features_processed
            )
        )
        if fixed_geometries > 0:
            feedback.pushInfo(
                self.tr("Fixed {} invalid geometries").format(fixed_geometries)
            )
        if invalid_geometries > 0:
            feedback.reportError(
                self.tr("Skipped {} features with unfixable geometries").format(
                    invalid_geometries
                )
            )
        if wrong_geometry_type > 0:
            feedback.reportError(
                self.tr("Skipped {} features with wrong geometry type").format(
                    wrong_geometry_type
                )
            )

        # Get the processed layer
        processed_layer = context.getMapLayer(dest_id)
        if not processed_layer:
            raise QgsProcessingException(self.tr("Could not retrieve processed layer"))

        return processed_layer, source_crs

    def _prepare_field_mappings(
        self,
        processed_layer: QgsVectorLayer,
        feedback: QgsProcessingFeedback,
        allowed_fields: Optional[Set[str]] = None,
    ) -> QgsVectorLayer:
        """Normalize field names for PostgreSQL/PostGIS compatibility"""
        # Normalize field names
        valid_fields_mapping = {}
        for field in processed_layer.fields():
            if allowed_fields is not None and field.name() not in allowed_fields:
                continue

            # validate field type
            if field.type() not in [
                QVariant.String,
                QVariant.Int,
                QVariant.Double,
                QVariant.Bool,
            ]:
                feedback.pushInfo(
                    self.tr(
                        "Unsupported field type for field '{}'. "
                        "Only string, integer, float, and boolean fields are supported."
                    ).format(field.name())
                )
                continue  # Skip unsupported field types

            # validate field name
            normalized_name = normalize_field_name(field.name())
            if normalized_name:
                valid_fields_mapping[field.name()] = normalized_name
                feedback.pushInfo(
                    self.tr("Field '{}' normalized to '{}'").format(
                        field.name(), normalized_name
                    )
                )

        return rename_field_with_refactor(processed_layer, valid_fields_mapping)

    def _create_vector_and_attributes(
        self,
        project_id: str,
        vector_name: str,
        vector_type: str,
        attr_dict: Dict[str, str],
        feedback: QgsProcessingFeedback,
    ):
        """Create vector in STRATO and add attributes"""
        # Create vector
        options = api.project_vector.AddVectorOptions(
            name=vector_name,
            type=vector_type,
        )
        vector = api.project_vector.add_vector(project_id, options)
        feedback.pushInfo(
            self.tr("Created vector layer '{}' with ID: {}").format(
                vector_name, vector.id
            )
        )
        api.qgis_vector.add_attributes(vector_id=vector.id, attributes=attr_dict)
        feedback.pushInfo(
            self.tr("Added attributes to vector layer '{}': {}").format(
                vector_name, ", ".join(attr_dict.keys())
            )
        )
        return vector

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
