from typing import Any, Dict, Optional, Tuple, cast

from PyQt5.QtCore import QCoreApplication
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
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsVectorLayer,
    QgsWkbTypes,
)

from ...qgishub import api
from ...qgishub.get_token import get_token
from ..feature_uploader import FeatureUploader
from ..field_name_normalizer import FieldNameNormalizer
from ..vector_creator import VectorCreator


class UploadVectorAlgorithm(QgsProcessingAlgorithm):
    """Algorithm to upload vector layer to STRATO backend"""

    INPUT_LAYER: str = "INPUT"
    STRATO_PROJECT: str = "PROJECT"
    VECTOR_NAME: str = "VECTOR_NAME"
    OUTPUT: str = "OUTPUT"  # Hidden output for internal processing

    MAX_FIELD_COUNT: int = 10
    MAX_FEATURE_COUNT: int = 1000000

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
            "- Automatically normalize field names for PostgreSQL/PostGIS compatibility (lowercase, remove special characters)\n"
            "- Automatically check and fix invalid geometries before processing\n"
            "- Automatically convert multipart geometries to single parts and reproject to EPSG:4326 in one efficient step\n"
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

        # Process layer: convert to singlepart and reproject in one step
        processed_layer, original_crs = self._process_layer_geometry(
            layer, is_multipart, parameters, context, feedback
        )

        # Setup field name normalization
        normalizer = FieldNameNormalizer(processed_layer, feedback)

        # Check normalized field count limit
        normalized_field_count = len(normalizer.columns)
        if normalized_field_count > self.MAX_FIELD_COUNT:
            raise QgsProcessingException(
                self.tr(
                    f"After field normalization, the layer has {normalized_field_count} valid fields, "
                    f"but only up to {self.MAX_FIELD_COUNT} fields are supported."
                )
            )

        # Create vector in STRATO
        creator = VectorCreator(feedback)
        vector_id = creator.create_vector(project_id, vector_name, vector_type)

        # Create uploader and setup attribute schema
        uploader = FeatureUploader(vector_id, normalizer, original_crs, feedback)
        uploader.setup_attribute_schema()

        # Upload features to STRATO
        uploaded_feature_count = uploader.upload_layer(processed_layer)

        feedback.pushInfo(
            self.tr(f"Upload complete: {uploaded_feature_count} features")
        )

        return {"VECTOR_ID": vector_id}

    def _validate_and_get_parameters(
        self, parameters: Dict[str, Any], context: QgsProcessingContext
    ) -> Tuple[QgsVectorLayer, str, str]:
        """Validate parameters and return extracted values"""
        layer = self.parameterAsVectorLayer(parameters, self.INPUT_LAYER, context)
        project_index = self.parameterAsEnum(parameters, self.STRATO_PROJECT, context)
        vector_name = self.parameterAsString(parameters, self.VECTOR_NAME, context)

        if not layer:
            raise QgsProcessingException(self.tr("Invalid input layer"))

        # Check feature count limit
        feature_count = layer.featureCount()

        if feature_count > self.MAX_FEATURE_COUNT:
            raise QgsProcessingException(
                self.tr(
                    f"The input layer has too many features ({feature_count:,}).\n"
                    f"Maximum allowed is {self.MAX_FEATURE_COUNT:,} features."
                )
            )

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

    def _is_geometry_type_consistent(self, geometry, expected_type):
        """check if geometry type matches expected type"""
        if not geometry:
            return False

        actual_type = QgsWkbTypes.geometryType(geometry.wkbType())
        return actual_type == expected_type

    def _process_layer_geometry(
        self,
        layer: QgsVectorLayer,
        is_multipart: bool,
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
                self.tr(f"Reprojecting from {source_crs.authid()} to EPSG:4326")
            )

        feedback.pushInfo(self.tr("Processing layer: ") + ", ".join(processing_steps))

        # Get the target geometry type (always single part)
        target_wkb_type = QgsWkbTypes.singleType(layer.wkbType())
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
                    if not self._is_geometry_type_consistent(
                        single_geometry_part, expected_geom_type
                    ):
                        wrong_geometry_type += 1
                        continue  # Skip parts with wrong geometry type

                    # Create new feature for each part
                    new_feature = QgsFeature(feature)

                    # Transform if needed
                    if transform:
                        single_geometry_part.transform(transform)

                    new_feature.setGeometry(single_geometry_part)

                    # Add to sink
                    if not sink.addFeature(new_feature, QgsFeatureSink.FastInsert):
                        raise QgsProcessingException(
                            self.tr("Error processing feature")
                        )
                    features_processed += 1
            else:
                # Check geometry type consistency
                if not self._is_geometry_type_consistent(geom, expected_geom_type):
                    wrong_geometry_type += 1
                    continue  # Skip features with wrong geometry type

                # Single part geometry
                new_feature = QgsFeature(feature)

                # Transform if needed
                if transform:
                    geom = QgsGeometry(geom)  # Make a copy
                    geom.transform(transform)
                    new_feature.setGeometry(geom)

                # Add to sink
                if not sink.addFeature(new_feature, QgsFeatureSink.FastInsert):
                    raise QgsProcessingException(self.tr("Error processing feature"))
                features_processed += 1

            # Update progress (0-50% for geometry processing)
            if total_features > 0:
                progress = int((current + 1) / total_features * 50)
                feedback.setProgress(progress)

        feedback.pushInfo(
            self.tr(
                f"Geometry processing completed: {features_processed} features processed"
            )
        )
        if fixed_geometries > 0:
            feedback.pushInfo(self.tr(f"Fixed {fixed_geometries} invalid geometries"))
        if invalid_geometries > 0:
            feedback.reportError(
                self.tr(
                    f"Skipped {invalid_geometries} features with unfixable geometries"
                )
            )
        if wrong_geometry_type > 0:
            feedback.reportError(
                self.tr(
                    f"Skipped {wrong_geometry_type} features with wrong geometry type"
                )
            )

        # Get the processed layer
        processed_layer = context.getMapLayer(dest_id)
        if not processed_layer:
            raise QgsProcessingException(self.tr("Could not retrieve processed layer"))

        return processed_layer, source_crs
