import os

from qgis.core import QgsProcessingProvider

from ..kumoy.constants import PLUGIN_NAME
from ..ui.icons import MAIN_ICON
from .upload_vector.algorithm import UploadVectorAlgorithm


class KumoyProcessingProvider(QgsProcessingProvider):
    """Processing provider for KUMOY plugin"""

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
