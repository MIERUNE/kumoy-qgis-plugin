import os

from qgis.core import QgsApplication, QgsProviderRegistry
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QCoreApplication, QTranslator

from .browser.root import DataItemProvider
from .processing.provider import StratoProcessingProvider
from .strato.constants import PLUGIN_NAME
from .strato.provider.dataprovider_metadata import StratoProviderMetadata


class StratoPlugin:
    def __init__(self, iface: QgisInterface):
        self.iface = iface
        self.win = self.iface.mainWindow()
        self.plugin_dir = os.path.dirname(__file__)

        # Initialize translation
        self.translator = None
        self.init_translation()

        registry = QgsProviderRegistry.instance()
        metadata = StratoProviderMetadata()
        # FIXME: It is not possible to remove unregister a provider
        # Is it the correct approach?
        # assert registry.registerProvider(metadata)
        registry.registerProvider(metadata)

        # Initialize processing provider
        self.processing_provider = None

    def init_translation(self):
        """Initialize translation for the plugin"""
        locale = QgsApplication.instance().locale()
        locale_path = os.path.join(self.plugin_dir, "i18n", f"strato_{locale}.qm")

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

    def tr(self, message):
        """Get the translation for a string using Qt translation API"""
        return QCoreApplication.translate(PLUGIN_NAME, message)

    def initGui(self):
        self.dip = DataItemProvider()
        QgsApplication.instance().dataItemProviderRegistry().addProvider(self.dip)

        # Register processing provider
        self.processing_provider = StratoProcessingProvider()
        QgsApplication.processingRegistry().addProvider(self.processing_provider)

    def unload(self):
        # Remove translator
        if self.translator:
            QCoreApplication.removeTranslator(self.translator)

        QgsApplication.instance().dataItemProviderRegistry().removeProvider(self.dip)

        # Unregister processing provider
        if self.processing_provider:
            QgsApplication.processingRegistry().removeProvider(self.processing_provider)
