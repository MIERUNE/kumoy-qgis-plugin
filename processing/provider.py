"""
STRATO Processing provider
"""

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .upload_vector_algorithm import UploadVectorAlgorithm


class StratoProcessingProvider(QgsProcessingProvider):
    """Processing provider for STRATO plugin"""

    def __init__(self):
        super().__init__()

    def id(self):
        """Unique ID for this provider"""
        return "strato"

    def name(self):
        """Human-readable name for this provider"""
        return "STRATO"

    def icon(self):
        """Icon for this provider"""
        return QIcon(":/plugins/qgis-hub/imgs/icon.png")

    def loadAlgorithms(self):
        """Load algorithms"""
        self.addAlgorithm(UploadVectorAlgorithm())

    def longName(self):
        """Longer version of the provider name"""
        return self.name()