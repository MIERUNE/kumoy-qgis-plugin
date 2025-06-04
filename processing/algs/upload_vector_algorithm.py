from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple, cast

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


@dataclass
class GeometryAnalysisResult:
    """Analysis results for layer geometry characteristics"""

    vector_type: Literal["POINT", "LINESTRING", "POLYGON"]
    is_multipart: bool
    total_features: int


@dataclass
class ProcessingRequirements:
    """Requirements for geometry processing"""

    needs_singlepart: bool
    needs_reprojection: bool
    source_crs: QgsCoordinateReferenceSystem
    target_crs: QgsCoordinateReferenceSystem


class GeometryProcessor:
    """Handles geometry processing operations for a single layer"""

    def __init__(self, requirements: ProcessingRequirements, transform_context):
        self.requirements = requirements
        self.transform = None
        if requirements.needs_reprojection:
            self.transform = QgsCoordinateTransform(
                requirements.source_crs, requirements.target_crs, transform_context
            )
        
        # Statistics
        self.fixed_geometries = 0
        self.unfixable_geometries = 0

    def process_feature_geometry(self, feature: QgsFeature) -> List[QgsFeature]:
        """Process a single feature and return list of resulting features"""
        if not feature.hasGeometry():
            return []

        geom = feature.geometry()

        # Fix invalid geometry if needed
        if not geom.isGeosValid():
            fixed_geom = geom.makeValid()
            if not fixed_geom.isGeosValid():
                self.unfixable_geometries += 1
                return []  # Skip unfixable geometries
            geom = fixed_geom
            self.fixed_geometries += 1

        # Handle multipart to singlepart conversion
        if self.requirements.needs_singlepart and geom.isMultipart():
            return self._convert_multipart_feature(feature, geom)
        else:
            return [self._process_single_geometry(feature, geom)]

    def _convert_multipart_feature(
        self, feature: QgsFeature, geom: QgsGeometry
    ) -> List[QgsFeature]:
        """Convert multipart feature to multiple singlepart features"""
        result_features = []
        single_geometry_parts = geom.asGeometryCollection()

        for single_geometry_part in single_geometry_parts:
            # Fix geometry part if needed
            if not single_geometry_part.isGeosValid():
                fixed_part = single_geometry_part.makeValid()
                if not fixed_part.isGeosValid():
                    self.unfixable_geometries += 1
                    continue  # Skip unfixable parts
                single_geometry_part = fixed_part
                self.fixed_geometries += 1

            new_feature = QgsFeature(feature)
            processed_geom = self._transform_geometry(single_geometry_part)
            new_feature.setGeometry(processed_geom)
            result_features.append(new_feature)

        return result_features

    def _process_single_geometry(
        self, feature: QgsFeature, geom: QgsGeometry
    ) -> QgsFeature:
        """Process single geometry feature"""
        new_feature = QgsFeature(feature)
        processed_geom = self._transform_geometry(geom)
        new_feature.setGeometry(processed_geom)
        return new_feature

    def _transform_geometry(self, geom: QgsGeometry) -> QgsGeometry:
        """Apply coordinate transformation if needed"""
        if self.transform:
            geom = QgsGeometry(geom)  # Make a copy
            geom.transform(self.transform)
        return geom


class UploadVectorAlgorithm(QgsProcessingAlgorithm):
    """Algorithm to upload vector layer to STRATO backend"""

    INPUT_LAYER: str = "INPUT"
    STRATO_PROJECT: str = "PROJECT"
    VECTOR_NAME: str = "VECTOR_NAME"
    OUTPUT: str = "OUTPUT"  # Hidden output for internal processing

    MAX_FIELD_COUNT: int = 10

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
            "- Automatically fix invalid geometries before processing\n"
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

        # Analyze layer geometry characteristics
        geometry_analysis_result = self._analyze_layer_geometry(layer, feedback)

        # Process layer: fix geometries, convert to singlepart and reproject in one step
        processed_layer, original_crs = self._process_layer_geometry(
            layer, geometry_analysis_result, parameters, context, feedback
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
        vector_id = creator.create_vector(
            project_id, vector_name, geometry_analysis_result.vector_type
        )

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

    def _analyze_layer_geometry(
        self, layer: QgsVectorLayer, feedback: QgsProcessingFeedback
    ) -> GeometryAnalysisResult:
        """Analyze layer geometry characteristics by examining actual features"""
        wkb_type = layer.wkbType()
        is_multipart = False
        vector_type = ""

        # Determine base geometry type from WKB type
        if wkb_type in [QgsWkbTypes.Point, QgsWkbTypes.MultiPoint]:
            vector_type = "POINT"
            is_multipart = wkb_type == QgsWkbTypes.MultiPoint
        elif wkb_type in [QgsWkbTypes.LineString, QgsWkbTypes.MultiLineString]:
            vector_type = "LINESTRING"
            is_multipart = wkb_type == QgsWkbTypes.MultiLineString
        elif wkb_type in [QgsWkbTypes.Polygon, QgsWkbTypes.MultiPolygon]:
            vector_type = "POLYGON"
            is_multipart = wkb_type == QgsWkbTypes.MultiPolygon
        else:
            raise QgsProcessingException(self.tr("Unsupported geometry type"))

        total_features = layer.featureCount()
        
        feedback.pushInfo(self.tr("Analyzing layer geometry..."))
        return GeometryAnalysisResult(
            vector_type=vector_type,
            is_multipart=is_multipart,
            total_features=total_features,
        )

    def _determine_processing_requirements(
        self, layer: QgsVectorLayer, analysis: GeometryAnalysisResult
    ) -> ProcessingRequirements:
        """Determine what processing steps are needed"""
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

        return ProcessingRequirements(
            needs_singlepart=analysis.is_multipart,
            needs_reprojection=source_crs.authid() != "EPSG:4326",
            source_crs=source_crs,
            target_crs=target_crs,
        )

    def _create_processing_sink(
        self,
        layer: QgsVectorLayer,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
    ) -> Tuple[QgsFeatureSink, str]:
        """Create output sink for processed features"""
        target_wkb_type = QgsWkbTypes.singleType(layer.wkbType())
        target_crs = QgsCoordinateReferenceSystem("EPSG:4326")

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

        return sink, dest_id

    def _process_layer_geometry(
        self,
        layer: QgsVectorLayer,
        analysis: GeometryAnalysisResult,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Tuple[QgsVectorLayer, QgsCoordinateReferenceSystem]:
        """Process layer geometry using modular approach"""
        requirements = self._determine_processing_requirements(layer, analysis)

        # Always process through GeometryProcessor to handle invalid geometries
        # Even if no coordinate transformation or multipart conversion is needed
        
        # Log processing steps
        processing_steps = [self.tr("Validating and fixing geometries")]
        if requirements.needs_singlepart:
            processing_steps.append(self.tr("Converting multipart to singlepart"))
        if requirements.needs_reprojection:
            processing_steps.append(
                self.tr(f"Reprojecting from {requirements.source_crs.authid()} to EPSG:4326")
            )

        feedback.pushInfo(self.tr("Processing layer: ") + ", ".join(processing_steps))

        # Create processing components
        sink, dest_id = self._create_processing_sink(layer, parameters, context)
        processor = GeometryProcessor(requirements, context.transformContext())

        return self._process_features(
            layer, processor, sink, dest_id, requirements, context, feedback
        )

    def _process_features(
        self,
        layer: QgsVectorLayer,
        processor: GeometryProcessor,
        sink: QgsFeatureSink,
        dest_id: str,
        requirements: ProcessingRequirements,
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Tuple[QgsVectorLayer, QgsCoordinateReferenceSystem]:
        """Process all features through the geometry processor"""
        total_features = layer.featureCount()
        features_processed = 0
        invalid_count = 0

        for current, feature in enumerate(layer.getFeatures()):
            feature = cast(QgsFeature, feature)
            if feedback.isCanceled():
                break

            # Process feature through geometry processor
            processed_features = processor.process_feature_geometry(feature)

            # Count statistics
            if not processed_features and feature.hasGeometry():
                invalid_count += 1  # Feature was skipped due to unfixable geometry

            for processed_feature in processed_features:
                # Add to sink
                if not sink.addFeature(processed_feature, QgsFeatureSink.FastInsert):
                    raise QgsProcessingException(self.tr("Error processing feature"))
                features_processed += 1

            # Update progress (0-100% for geometry processing)
            if total_features > 0:
                progress = int((current + 1) / total_features * 100)
                feedback.setProgress(progress)

        # Log processing results
        feedback.pushInfo(
            self.tr(f"Geometry processing completed: {features_processed} features processed")
        )
        if processor.fixed_geometries > 0:
            feedback.pushInfo(
                self.tr(f"Fixed {processor.fixed_geometries} invalid geometries")
            )
        if processor.unfixable_geometries > 0:
            feedback.reportError(
                self.tr(f"Skipped {processor.unfixable_geometries} features with unfixable geometries")
            )

        # Get the processed layer
        processed_layer = context.getMapLayer(dest_id)
        if not processed_layer:
            raise QgsProcessingException(self.tr("Could not retrieve processed layer"))

        return processed_layer, requirements.source_crs
