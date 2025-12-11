import os

from qgis.core import QgsProcessingProvider

from ..imgs import MAIN_ICON, DARK_MODE_ICON
from ..kumoy.constants import PLUGIN_NAME
from ..ui.browser.utils import is_in_darkmode
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
        return DARK_MODE_ICON if is_in_darkmode() else MAIN_ICON

    def loadAlgorithms(self):
        """Load algorithms"""
        self.addAlgorithm(UploadVectorAlgorithm())

    def longName(self):
        """Longer version of the provider name"""
        return self.name()
