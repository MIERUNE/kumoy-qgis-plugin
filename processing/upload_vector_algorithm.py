"""
Upload vector layer to STRATO backend
"""

from typing import Dict

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
    QgsProcessingException,
    QgsProcessingParameterEnum,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsVectorLayer,
    QgsWkbTypes,
)

import processing

from ..qgishub.api.organization import get_organizations
from ..qgishub.api.project import get_projects_by_organization
from ..qgishub.api.project_vector import AddVectorOptions, add_vector
from ..qgishub.api.qgis_vector import add_attributes, add_features
from ..qgishub.get_token import get_token


class UploadVectorAlgorithm(QgsProcessingAlgorithm):
    """Algorithm to upload vector layer to STRATO backend"""

    INPUT = "INPUT"
    PROJECT = "PROJECT"
    VECTOR_NAME = "VECTOR_NAME"

    def tr(self, string):
        """Translate string"""
        return QCoreApplication.translate("Processing", string)

    def createInstance(self):
        """Create new instance of algorithm"""
        return UploadVectorAlgorithm()

    def name(self):
        """Algorithm name"""
        return "uploadvector"

    def displayName(self):
        """Algorithm display name"""
        return self.tr("Upload Vector Layer to STRATO")

    def group(self):
        """Algorithm group"""
        return self.tr("Tools")

    def groupId(self):
        """Algorithm group ID"""
        return "Tools"

    def shortHelpString(self):
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
            "- Upload all features in batches (1000 features per batch)\n"
            "- Show progress during the upload\n\n"
            "Note: You must be logged in to STRATO before using this tool."
        )

    def initAlgorithm(self, config=None):
        """Initialize algorithm parameters"""
        # Input vector layer
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT,
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
                self.PROJECT,
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

    def processAlgorithm(self, parameters, context, feedback):
        """Process the algorithm"""
        # Get parameters
        layer = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        project_index = self.parameterAsEnum(parameters, self.PROJECT, context)
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

        # Check authentication
        token = get_token()
        if not token:
            raise QgsProcessingException(
                self.tr("Authentication required. Please login from plugin settings.")
            )

        # Determine geometry type and check for multipart
        wkb_type = layer.wkbType()
        is_multipart = False

        if wkb_type in [
            QgsWkbTypes.Point,
        ]:
            vector_type = "POINT"
        elif wkb_type in [
            QgsWkbTypes.MultiPoint,
        ]:
            vector_type = "POINT"
            is_multipart = True
        elif wkb_type in [
            QgsWkbTypes.LineString,
        ]:
            vector_type = "LINESTRING"
        elif wkb_type in [
            QgsWkbTypes.MultiLineString,
        ]:
            vector_type = "LINESTRING"
            is_multipart = True
        elif wkb_type in [
            QgsWkbTypes.Polygon,
        ]:
            vector_type = "POLYGON"
        elif wkb_type in [
            QgsWkbTypes.MultiPolygon,
        ]:
            vector_type = "POLYGON"
            is_multipart = True
        else:
            raise QgsProcessingException(self.tr("Unsupported geometry type"))

        # Convert multipart to singlepart if needed
        processing_layer = layer
        if is_multipart:
            feedback.pushInfo(
                self.tr("Detected multipart geometry. Converting to single parts...")
            )
            result = processing.run(
                "native:multiparttosingleparts",
                {"INPUT": layer, "OUTPUT": "TEMPORARY_OUTPUT"},
                context=context,
                feedback=feedback,
            )
            processing_layer = result["OUTPUT"]
            feedback.pushInfo(self.tr("Conversion to single parts completed."))

        # Create a temporary layer with EPSG:4326 if reprojection is needed
        crs = processing_layer.crs()
        target_crs = QgsCoordinateReferenceSystem("EPSG:4326")

        if crs.authid() != "EPSG:4326":
            feedback.pushInfo(
                self.tr(f"Reprojecting from {crs.authid()} to EPSG:4326...")
            )

            # Get the single-part geometry type for the memory layer
            single_wkb_type = QgsWkbTypes.singleType(processing_layer.wkbType())

            # Create a temporary memory layer with EPSG:4326
            memory_layer_uri = QgsMemoryProviderUtils.createMemoryLayer(
                "temp_4326", processing_layer.fields(), single_wkb_type, target_crs
            )

            # Get coordinate transform
            transform = QgsCoordinateTransform(crs, target_crs, context.project())
            
            # Use data provider as sink
            sink = memory_layer_uri.dataProvider()

            # Copy features with coordinate transformation
            features = list(processing_layer.getFeatures())
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

            processing_layer = memory_layer_uri
            feedback.pushInfo(self.tr("Reprojection completed."))

        feedback.pushInfo(
            self.tr(f"Creating {vector_type} layer in project {project_id}...")
        )

        # Create vector in project
        try:
            add_options = AddVectorOptions(name=vector_name, type=vector_type)
            new_vector = add_vector(project_id, add_options)

            if not new_vector:
                raise QgsProcessingException(self.tr("Failed to create vector layer"))

            vector_id = new_vector.id
            feedback.pushInfo(self.tr(f"Vector layer created: {vector_id}"))

        except Exception as e:
            raise QgsProcessingException(
                self.tr(f"Error creating vector layer: {str(e)}")
            )

        # Define column schema
        feedback.pushInfo(self.tr("Setting up attribute schema..."))
        columns = self._get_column_schema(processing_layer, feedback)

        if columns:
            try:
                success = add_attributes(vector_id, columns)
                if not success:
                    feedback.reportError(self.tr("Failed to set attribute schema"))
            except Exception as e:
                feedback.reportError(self.tr(f"Attribute schema error: {str(e)}"))

        # Upload features
        feedback.pushInfo(self.tr("Uploading features..."))
        total_features = processing_layer.featureCount()

        if total_features == 0:
            feedback.pushInfo(self.tr("No features to upload"))
            return {"VECTOR_ID": vector_id}

        # Create supported fields for upload
        upload_fields = QgsFields()
        for field in processing_layer.fields():
            if field.name() in columns:
                upload_fields.append(QgsField(field))

        # Process features in batches
        batch_size = 1000
        features_uploaded = 0
        batch = []

        # Track if reprojection was done for progress calculation
        reprojection_done = crs.authid() != "EPSG:4326"

        try:
            for feature in processing_layer.getFeatures():
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

                batch.append(new_feature)

                # Upload batch when it reaches the size limit
                if len(batch) >= batch_size:
                    success = add_features(vector_id, batch)
                    if not success:
                        raise QgsProcessingException(
                            self.tr("Failed to upload features")
                        )

                    features_uploaded += len(batch)
                    # Adjust progress to account for reprojection if it was done
                    if reprojection_done:
                        progress = 50 + int((features_uploaded / total_features) * 50)
                    else:
                        progress = int((features_uploaded / total_features) * 100)
                    feedback.setProgress(progress)
                    feedback.pushInfo(
                        self.tr(
                            f"Progress: {features_uploaded}/{total_features} features"
                        )
                    )
                    batch = []

            # Upload remaining features
            if batch:
                success = add_features(vector_id, batch)
                if not success:
                    raise QgsProcessingException(self.tr("Failed to upload features"))
                features_uploaded += len(batch)

        except Exception as e:
            raise QgsProcessingException(self.tr(f"Error uploading features: {str(e)}"))

        feedback.pushInfo(self.tr(f"Upload complete: {features_uploaded} features"))

        return {"VECTOR_ID": vector_id}

    def _get_column_schema(
        self, layer: QgsVectorLayer, feedback=None
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
