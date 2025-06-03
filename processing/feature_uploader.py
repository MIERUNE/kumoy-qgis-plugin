"""
Feature uploader for STRATO backend
"""

from typing import Dict, List, Optional

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsProcessingFeedback,
    QgsVectorLayer,
)

from ..qgishub import api
from .field_name_normalizer import FieldNameNormalizer


class FeatureUploader:
    """Handles feature upload to STRATO backend with field name normalization"""

    def __init__(
        self,
        vector_id: str,
        normalizer: FieldNameNormalizer,
        original_crs: Optional[QgsCoordinateReferenceSystem] = None,
        feedback: Optional[QgsProcessingFeedback] = None,
        page_size: int = 1000,
    ):
        """Initialize the feature uploader

        Args:
            vector_id: The ID of the vector layer in STRATO
            normalizer: The field name normalizer instance
            original_crs: The original CRS of the layer (for progress calculation)
            feedback: Optional feedback object for progress reporting
            page_size: Number of features to upload in each batch
        """
        self.vector_id = vector_id
        self.normalizer = normalizer
        self.original_crs = original_crs
        self.feedback = feedback
        self.page_size = page_size
        self.features_uploaded = 0
        self.upload_fields = normalizer.get_normalized_fields()

    def upload_layer(self, layer: QgsVectorLayer) -> int:
        """Upload all features from a layer

        Args:
            layer: The layer to upload features from

        Returns:
            Number of features uploaded
        """
        if self.feedback:
            self.feedback.pushInfo(self.tr("Uploading features..."))

        total_features = layer.featureCount()

        if total_features == 0:
            if self.feedback:
                self.feedback.pushInfo(self.tr("No features to upload"))
            return 0

        # Process features in chunks
        chunk = []

        try:
            for feature in layer.getFeatures():
                if self.feedback and self.feedback.isCanceled():
                    break

                # Skip features without geometry
                if not feature.hasGeometry():
                    continue

                # Create normalized feature
                normalized_feature = self._create_normalized_feature(feature)
                chunk.append(normalized_feature)

                # Upload chunk when it reaches the size limit
                if len(chunk) >= self.page_size:
                    self._upload_chunk(chunk, total_features)
                    chunk = []

            # Upload remaining features
            if chunk:
                self._upload_chunk(chunk, total_features)

        except Exception as e:
            from qgis.core import QgsProcessingException

            raise QgsProcessingException(self.tr(f"Error uploading features: {str(e)}"))

        return self.features_uploaded

    def setup_attribute_schema(self) -> bool:
        """Setup attribute schema on STRATO

        Returns:
            True if successful, False otherwise
        """
        if self.feedback:
            self.feedback.pushInfo(self.tr("Setting up attribute schema..."))

        columns = self.normalizer.columns

        if columns:
            try:
                success = api.qgis_vector.add_attributes(self.vector_id, columns)
                if not success and self.feedback:
                    self.feedback.reportError(self.tr("Failed to set attribute schema"))
                return success
            except Exception as e:
                if self.feedback:
                    self.feedback.reportError(
                        self.tr(f"Attribute schema error: {str(e)}")
                    )
                return False

        return True

    def _create_normalized_feature(self, original_feature: QgsFeature) -> QgsFeature:
        """Create a feature with normalized field names

        Args:
            original_feature: The original feature

        Returns:
            A new feature with normalized field names
        """
        new_feature = QgsFeature()
        new_feature.setGeometry(original_feature.geometry())
        new_feature.setFields(self.upload_fields)

        # Map attributes from original to normalized names
        for field in self.upload_fields:
            normalized_name = field.name()
            original_name = self.normalizer.normalized_to_original[normalized_name]
            new_feature.setAttribute(
                normalized_name, original_feature.attribute(original_name)
            )

        return new_feature

    def _upload_chunk(self, chunk: List[QgsFeature], total_features: int) -> None:
        """Upload a chunk of features to STRATO

        Args:
            chunk: List of features to upload
            total_features: Total number of features (for progress)
        """
        success = api.qgis_vector.add_features(self.vector_id, chunk)
        if not success:
            from qgis.core import QgsProcessingException

            raise QgsProcessingException(self.tr("Failed to upload features"))

        self.features_uploaded += len(chunk)

        if self.feedback:
            # Calculate progress
            progress = self._calculate_progress(self.features_uploaded, total_features)
            self.feedback.setProgress(progress)
            self.feedback.pushInfo(
                self.tr(f"Progress: {self.features_uploaded}/{total_features} features")
            )

    def _calculate_progress(self, current: int, total: int) -> int:
        """Calculate progress percentage

        Args:
            current: Current number of features processed
            total: Total number of features

        Returns:
            Progress percentage (0-100)
        """
        if total == 0:
            return 100

        # If reprojection was done, upload progress is 50-100%
        # Otherwise, upload progress is 0-100%
        if self.original_crs and self.original_crs.authid() != "EPSG:4326":
            return 50 + int((current / total) * 50)
        else:
            return int((current / total) * 100)

    def tr(self, string: str) -> str:
        """Translate string"""
        from PyQt5.QtCore import QCoreApplication

        return QCoreApplication.translate("FeatureUploader", string)
