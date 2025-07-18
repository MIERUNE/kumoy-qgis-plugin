from typing import Optional

from qgis.core import QgsProcessingFeedback

from ..strato import api
from ..strato.api.project_vector import AddVectorOptions


class VectorCreator:
    """Creates vector layers in STRATO backend"""

    def __init__(self, feedback: Optional[QgsProcessingFeedback] = None):
        """Initialize the vector creator

        Args:
            feedback: Optional feedback object for progress reporting
        """
        self.feedback = feedback

    def create_vector(self, project_id: str, vector_name: str, vector_type: str) -> str:
        """Create a new vector layer in STRATO

        Args:
            project_id: The ID of the project to create the vector in
            vector_name: The name of the vector layer
            vector_type: The geometry type (POINT, LINESTRING, POLYGON)

        Returns:
            The ID of the created vector layer

        Raises:
            QgsProcessingException: If vector creation fails
        """
        if self.feedback:
            self.feedback.pushInfo(
                self.tr(f"Creating {vector_type} layer in project {project_id}...")
            )

        try:
            add_options = AddVectorOptions(name=vector_name, type=vector_type)
            new_vector = api.project_vector.add_vector(project_id, add_options)

            if not new_vector:
                from qgis.core import QgsProcessingException

                raise QgsProcessingException(self.tr("Failed to create vector layer"))

            vector_id = new_vector.id
            if self.feedback:
                self.feedback.pushInfo(self.tr(f"Vector layer created: {vector_id}"))
            return vector_id

        except Exception as e:
            from qgis.core import QgsProcessingException

            raise QgsProcessingException(
                self.tr(f"Error creating vector layer: {str(e)}")
            )

    def tr(self, string: str) -> str:
        """Translate string"""
        from PyQt5.QtCore import QCoreApplication

        return QCoreApplication.translate("VectorCreator", string)
