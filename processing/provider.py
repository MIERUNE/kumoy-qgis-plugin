import os

from qgis.core import QgsProcessingProvider

from ..imgs import MAIN_ICON
from ..strato.constants import PLUGIN_NAME
from .upload_vector.algorithm import UploadVectorAlgorithm


class StratoProcessingProvider(QgsProcessingProvider):
    """Processing provider for STRATO plugin"""

    def __init__(self):
        super().__init__()

    def id(self):
        """Unique ID for this provider"""
        return PLUGIN_NAME.lower()

    def name(self):
        """Human-readable name for this provider"""
        return PLUGIN_NAME

    def icon(self):
        """Icon for this provider"""
        return MAIN_ICON

    def loadAlgorithms(self):
        """Load algorithms"""
        self.addAlgorithm(UploadVectorAlgorithm())

    def longName(self):
        """Longer version of the provider name"""
        return self.name()
