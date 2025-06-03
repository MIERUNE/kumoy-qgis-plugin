"""
Upload vector layer to STRATO backend
"""

from typing import Any, Dict, List, Optional, Tuple

from PyQt5.QtCore import QCoreApplication, QMetaType
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsMemoryProviderUtils,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingParameterEnum,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsVectorLayer,
    QgsWkbTypes,
)

import processing

from ..qgishub import api
from ..qgishub.api.organization import get_organizations
from ..qgishub.api.project import get_projects_by_organization
from ..qgishub.api.project_vector import AddVectorOptions
from ..qgishub.get_token import get_token


class UploadVectorAlgorithm(QgsProcessingAlgorithm):
    """Algorithm to upload vector layer to STRATO backend"""

    INPUT_LAYER: str = "INPUT"
    STRATO_PROJECT: str = "PROJECT"
    VECTOR_NAME: str = "VECTOR_NAME"

    project_map: Dict[str, str]

    def tr(self, string: str) -> str:
        """Translate string"""
        return QCoreApplication.translate("Processing", string)

    def createInstance(self) -> "UploadVectorAlgorithm":
        """Create new instance of algorithm"""
        return UploadVectorAlgorithm()

    def name(self) -> str:
        """Algorithm name"""
        return "uploadvector"

    def displayName(self) -> str:
        """Algorithm display name"""
        return self.tr("Upload Vector Layer to STRATO")

    def group(self) -> str:
        """Algorithm group"""
        return self.tr("Tools")

    def groupId(self) -> str:
        """Algorithm group ID"""
        return "Tools"

    def shortHelpString(self) -> str:
        """Short help string"""
        return self.tr(
            "Upload a vector layer to the STRATO backend.\n\n"
            "User operation steps:\n"
            "1. Select the vector layer you want to upload from the dropdown\n"
            "2. Choose the destination project from Organization/Project list\n"
            "3. (Optional) Enter a custom name for the vector layer, or leave empty to use the original layer name\n"
            "4. Click 'Run' to start the upload process\n\n"
            "The algorithm will:\n"
            "- Automatically convert multipart geometries (MultiPoint, MultiLineString, MultiPolygon) to single parts\n"
            "- Automatically reproject the layer to EPSG:4326 using QgsFeatureSink if needed\n"
            "- Create a new vector layer in the selected project\n"
            "- Configure the attribute schema based on your layer's fields\n"
            "- Upload all features in chunkes (1000 features per chunk)\n"
            "- Show progress during the upload\n\n"
            "Note: You must be logged in to STRATO before using this tool."
        )

    def initAlgorithm(self, config: Optional[Dict[str, Any]] = None) -> None:
        """Initialize algorithm parameters"""
        # Input vector layer
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_LAYER,
                self.tr("Input vector layer"),
                [QgsProcessing.TypeVector],
            )
        )

        # Get available projects
        try:
            token = get_token()
            if token:
                # Get all organizations first
                organizations = get_organizations()
                project_options = []
                project_ids = []

                # Get projects for each organization
                for org in organizations:
                    projects = get_projects_by_organization(org.id)
                    for project in projects:
                        project_options.append(f"{org.name} / {project.name}")
                        project_ids.append(project.id)

                self.project_map = dict(zip(project_options, project_ids))
            else:
                project_options = []
                self.project_map = {}
        except Exception as e:
            print(f"Error loading projects: {str(e)}")
            project_options = []
            self.project_map = {}

        # Project selection
        self.addParameter(
            QgsProcessingParameterEnum(
                self.STRATO_PROJECT,
                self.tr("Destination project"),
                options=project_options,
                allowMultiple=False,
                optional=False,
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

    def processAlgorithm(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        """Process the algorithm"""
        # Validate parameters and get basic info
        layer, project_id, vector_name = self._validate_and_get_parameters(
            parameters, context
        )

        # Check authentication
        self._check_authentication()

        # Determine geometry type
        vector_type, is_multipart = self._get_geometry_type(layer)

        # Convert multipart to singlepart if needed
        singlepart_layer = self._convert_to_singlepart(
            layer, is_multipart, context, feedback
        )

        # Reproject to EPSG:4326 if needed
        reprojected_layer, crs = self._reproject_to_wgs84(
            singlepart_layer, context, feedback
        )

        # Create vector in STRATO
        vector_id = self._create_vector_in_strato(
            project_id, vector_name, vector_type, feedback
        )

        # Setup attribute schema
        columns = self._setup_attribute_schema(reprojected_layer, vector_id, feedback)

        # Upload features to STRATO
        features_uploaded = self._upload_features(
            reprojected_layer, vector_id, columns, crs, feedback
        )

        feedback.pushInfo(self.tr(f"Upload complete: {features_uploaded} features"))

        return {"VECTOR_ID": vector_id}

    def _get_column_schema(
        self, layer: QgsVectorLayer, feedback: Optional[QgsProcessingFeedback] = None
    ) -> Dict[str, str]:
        """Get column schema from layer fields"""
        columns = {}
        skipped_fields = []

        # Type mapping using QMetaType (same as browser/vector.py)
        for field in layer.fields():
            if field.type() == QMetaType.Int:
                columns[field.name()] = "integer"
            elif field.type() == QMetaType.Double or field.type() == QMetaType.Float:
                columns[field.name()] = "float"
            elif field.type() == QMetaType.Bool:
                columns[field.name()] = "boolean"
            elif field.type() == QMetaType.QString:
                columns[field.name()] = "string"
            else:
                # Skip unsupported field types
                type_name = (
                    QMetaType.typeName(field.type()) if field.type() > 0 else "Unknown"
                )
                skipped_fields.append(f"{field.name()} (Type: {type_name})")
                continue

        # Report skipped fields
        if skipped_fields and feedback:
            feedback.pushWarning(
                self.tr(
                    "The following fields were skipped due to unsupported data types:"
                )
            )
            for skipped in skipped_fields:
                feedback.pushWarning(f"  - {skipped}")

        return columns

    def _validate_and_get_parameters(
        self, parameters: Dict[str, Any], context: QgsProcessingContext
    ) -> Tuple[QgsVectorLayer, str, str]:
        """Validate parameters and return extracted values"""
        layer = self.parameterAsVectorLayer(parameters, self.INPUT_LAYER, context)
        project_index = self.parameterAsEnum(parameters, self.STRATO_PROJECT, context)
        vector_name = self.parameterAsString(parameters, self.VECTOR_NAME, context)

        if not layer:
            raise QgsProcessingException(self.tr("Invalid input layer"))

        # Get project ID
        project_options = list(self.project_map.keys())
        if project_index >= len(project_options):
            raise QgsProcessingException(self.tr("Invalid project selection"))

        project_id = self.project_map[project_options[project_index]]

        # Use layer name if vector name not provided
        if not vector_name:
            vector_name = layer.name()

        return layer, project_id, vector_name

    def _check_authentication(self) -> None:
        """Check if user is authenticated"""
        token = get_token()
        if not token:
            raise QgsProcessingException(
                self.tr("Authentication required. Please login from plugin settings.")
            )

    def _get_geometry_type(self, layer: QgsVectorLayer) -> Tuple[str, bool]:
        """Determine geometry type and check for multipart"""
        wkb_type = layer.wkbType()
        is_multipart = False

        if wkb_type in [QgsWkbTypes.Point]:
            vector_type = "POINT"
        elif wkb_type in [QgsWkbTypes.MultiPoint]:
            vector_type = "POINT"
            is_multipart = True
        elif wkb_type in [QgsWkbTypes.LineString]:
            vector_type = "LINESTRING"
        elif wkb_type in [QgsWkbTypes.MultiLineString]:
            vector_type = "LINESTRING"
            is_multipart = True
        elif wkb_type in [QgsWkbTypes.Polygon]:
            vector_type = "POLYGON"
        elif wkb_type in [QgsWkbTypes.MultiPolygon]:
            vector_type = "POLYGON"
            is_multipart = True
        else:
            raise QgsProcessingException(self.tr("Unsupported geometry type"))

        return vector_type, is_multipart

    def _convert_to_singlepart(
        self,
        layer: QgsVectorLayer,
        is_multipart: bool,
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> QgsVectorLayer:
        """Convert multipart geometries to single parts if needed"""
        if not is_multipart:
            return layer

        feedback.pushInfo(
            self.tr("Detected multipart geometry. Converting to single parts...")
        )
        result = processing.run(
            "native:multiparttosingleparts",
            {"INPUT": layer, "OUTPUT": "TEMPORARY_OUTPUT"},
            context=context,
            feedback=feedback,
        )
        feedback.pushInfo(self.tr("Conversion to single parts completed."))
        return result["OUTPUT"]

    def _reproject_to_wgs84(
        self,
        layer: QgsVectorLayer,
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Tuple[QgsVectorLayer, QgsCoordinateReferenceSystem]:
        """Reproject layer to EPSG:4326 if needed"""
        crs = layer.crs()
        target_crs = QgsCoordinateReferenceSystem("EPSG:4326")

        if crs.authid() == "EPSG:4326":
            return layer, crs

        feedback.pushInfo(self.tr(f"Reprojecting from {crs.authid()} to EPSG:4326..."))

        # Get the single-part geometry type for the memory layer
        single_wkb_type = QgsWkbTypes.singleType(layer.wkbType())

        # Create a temporary memory layer with EPSG:4326
        memory_layer_uri = QgsMemoryProviderUtils.createMemoryLayer(
            "temp_4326", layer.fields(), single_wkb_type, target_crs
        )

        # Get coordinate transform
        transform = QgsCoordinateTransform(crs, target_crs, context.project())

        # Use data provider as sink
        sink = memory_layer_uri.dataProvider()

        # Copy features with coordinate transformation
        features = list(layer.getFeatures())
        total_features = len(features)

        for i, feature in enumerate(features):
            if feedback.isCanceled():
                break

            # Create a new feature and transform geometry
            new_feature = QgsFeature(feature)
            if new_feature.hasGeometry():
                geom = new_feature.geometry()
                geom.transform(transform)
                new_feature.setGeometry(geom)

            # Add transformed feature
            sink.addFeature(new_feature, QgsFeatureSink.FastInsert)

            # Update progress
            progress = int((i + 1) / total_features * 50)  # 0-50% for reprojection
            feedback.setProgress(progress)

        feedback.pushInfo(self.tr("Reprojection completed."))
        return memory_layer_uri, crs

    def _create_vector_in_strato(
        self,
        project_id: str,
        vector_name: str,
        vector_type: str,
        feedback: QgsProcessingFeedback,
    ) -> str:
        """Create a new vector layer in STRATO"""
        feedback.pushInfo(
            self.tr(f"Creating {vector_type} layer in project {project_id}...")
        )

        try:
            add_options = AddVectorOptions(name=vector_name, type=vector_type)
            new_vector = api.project_vector.add_vector(project_id, add_options)

            if not new_vector:
                raise QgsProcessingException(self.tr("Failed to create vector layer"))

            vector_id = new_vector.id
            feedback.pushInfo(self.tr(f"Vector layer created: {vector_id}"))
            return vector_id

        except Exception as e:
            raise QgsProcessingException(
                self.tr(f"Error creating vector layer: {str(e)}")
            )

    def _setup_attribute_schema(
        self, layer: QgsVectorLayer, vector_id: str, feedback: QgsProcessingFeedback
    ) -> Dict[str, str]:
        """Setup attribute schema for the vector layer"""
        feedback.pushInfo(self.tr("Setting up attribute schema..."))
        columns = self._get_column_schema(layer, feedback)

        if columns:
            try:
                success = api.qgis_vector.add_attributes(vector_id, columns)
                if not success:
                    feedback.reportError(self.tr("Failed to set attribute schema"))
            except Exception as e:
                feedback.reportError(self.tr(f"Attribute schema error: {str(e)}"))

        return columns

    def _upload_features(
        self,
        layer: QgsVectorLayer,
        vector_id: str,
        columns: Dict[str, str],
        original_crs: QgsCoordinateReferenceSystem,
        feedback: QgsProcessingFeedback,
    ) -> int:
        """Upload features to STRATO in chunkes"""
        feedback.pushInfo(self.tr("Uploading features..."))
        total_features = layer.featureCount()

        if total_features == 0:
            feedback.pushInfo(self.tr("No features to upload"))
            return 0

        # Create supported fields for upload
        upload_fields = QgsFields()
        for field in layer.fields():
            if field.name() in columns:
                upload_fields.append(QgsField(field))

        # Process features in chunkes
        # Note: 1000 is a reasonable default for most use cases
        # Smaller chunkes = more API calls but less memory usage
        # Larger chunkes = fewer API calls but more memory usage
        PAGE_SIZE = 1000
        features_uploaded = 0
        chunk = []

        # Track if reprojection was done for progress calculation
        reprojection_done = original_crs.authid() != "EPSG:4326"

        try:
            for feature in layer.getFeatures():
                if feedback.isCanceled():
                    break

                # Skip features without geometry
                if not feature.hasGeometry():
                    continue

                # Create new feature with only supported fields
                new_feature = QgsFeature()
                new_feature.setGeometry(feature.geometry())
                new_feature.setFields(upload_fields)

                for field in upload_fields:
                    new_feature.setAttribute(
                        field.name(), feature.attribute(field.name())
                    )

                chunk.append(new_feature)

                # Upload chunk when it reaches the size limit
                if len(chunk) >= PAGE_SIZE:
                    self._upload_chunk(
                        vector_id,
                        chunk,
                        features_uploaded,
                        total_features,
                        reprojection_done,
                        feedback,
                    )
                    features_uploaded += len(chunk)
                    chunk = []

            # Upload remaining features
            if chunk:
                self._upload_chunk(
                    vector_id,
                    chunk,
                    features_uploaded,
                    total_features,
                    reprojection_done,
                    feedback,
                )
                features_uploaded += len(chunk)

        except Exception as e:
            raise QgsProcessingException(self.tr(f"Error uploading features: {str(e)}"))

        return features_uploaded

    def _upload_chunk(
        self,
        vector_id: str,
        chunk: List[QgsFeature],
        features_uploaded: int,
        total_features: int,
        reprojection_done: bool,
        feedback: QgsProcessingFeedback,
    ) -> None:
        """Upload a chunk of features to STRATO"""
        success = api.qgis_vector.add_features(vector_id, chunk)
        if not success:
            raise QgsProcessingException(self.tr("Failed to upload features"))

        current_count = features_uploaded + len(chunk)

        # Adjust progress to account for reprojection if it was done
        if reprojection_done:
            progress = 50 + int((current_count / total_features) * 50)
        else:
            progress = int((current_count / total_features) * 100)

        feedback.setProgress(progress)
        feedback.pushInfo(
            self.tr(f"Progress: {current_count}/{total_features} features")
        )
