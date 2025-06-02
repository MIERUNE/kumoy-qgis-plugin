"""
Upload vector layer to STRATO backend
"""

from typing import Dict, List

from PyQt5.QtCore import QCoreApplication, QMetaType
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFields,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterEnum,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsVectorLayer,
    QgsWkbTypes,
)

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
        return "vector"

    def shortHelpString(self):
        """Short help string"""
        return self.tr(
            "Upload a vector layer to the STRATO backend.\n\n"
            "This algorithm performs the following steps:\n"
            "1. Create a new vector layer in the selected project\n"
            "2. Set up the layer's attribute schema\n"
            "3. Upload all features"
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

        # Determine geometry type
        wkb_type = layer.wkbType()

        if wkb_type in [
            QgsWkbTypes.Point,
            QgsWkbTypes.Point25D,
            QgsWkbTypes.PointZ,
            QgsWkbTypes.PointM,
            QgsWkbTypes.PointZM,
        ]:
            vector_type = "POINT"
        elif wkb_type in [
            QgsWkbTypes.LineString,
            QgsWkbTypes.LineString25D,
            QgsWkbTypes.LineStringZ,
            QgsWkbTypes.LineStringM,
            QgsWkbTypes.LineStringZM,
        ]:
            vector_type = "LINESTRING"
        elif wkb_type in [
            QgsWkbTypes.Polygon,
            QgsWkbTypes.Polygon25D,
            QgsWkbTypes.PolygonZ,
            QgsWkbTypes.PolygonM,
            QgsWkbTypes.PolygonZM,
        ]:
            vector_type = "POLYGON"
        else:
            raise QgsProcessingException(self.tr("Unsupported geometry type"))

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
        columns = self._get_column_schema(layer)

        if columns:
            try:
                success = add_attributes(vector_id, columns)
                if not success:
                    feedback.reportError(self.tr("Failed to set attribute schema"))
            except Exception as e:
                feedback.reportError(self.tr(f"Attribute schema error: {str(e)}"))

        # Upload features
        feedback.pushInfo(self.tr("Uploading features..."))
        total_features = layer.featureCount()

        if total_features == 0:
            feedback.pushInfo(self.tr("No features to upload"))
            return {"VECTOR_ID": vector_id}

        # Create supported fields for upload
        upload_fields = QgsFields()
        for field in layer.fields():
            if field.name() in columns:
                upload_fields.append(QgsField(field))

        # Process features in batches
        batch_size = 1000
        features_uploaded = 0
        batch = []

        try:
            for feature in layer.getFeatures():
                if feedback.isCanceled():
                    break

                # Skip features without geometry
                if not feature.hasGeometry():
                    continue

                # Skip features with different geometry type
                if feature.geometry().wkbType() != wkb_type:
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

    def _get_column_schema(self, layer: QgsVectorLayer) -> Dict[str, str]:
        """Get column schema from layer fields"""
        columns = {}

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
                continue

        return columns
