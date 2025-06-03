"""
STRATO Processing provider
"""

import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from qgishub.constants import PLUGIN_NAME

from ..imgs import IMGS_PATH
from .algs import UploadVectorAlgorithm


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
        return QIcon(os.path.join(IMGS_PATH, "icon.svg"))

    def loadAlgorithms(self):
        """Load algorithms"""
        self.addAlgorithm(UploadVectorAlgorithm())

    def longName(self):
        """Longer version of the provider name"""
        return self.name()
