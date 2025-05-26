import os

from qgis.core import QgsApplication, QgsProviderRegistry
from qgis.gui import QgisInterface

from .browser.root import DataItemProvider
from .qgishub.provider.dataprovider_metadata import QgishubProviderMetadata


class QgishubPlugin:
    def __init__(self, iface: QgisInterface):
        self.iface = iface
        self.win = self.iface.mainWindow()
        self.plugin_dir = os.path.dirname(__file__)

        registry = QgsProviderRegistry.instance()
        metadata = QgishubProviderMetadata()
        # FIXME: It is not possible to remove unregister a provider
        # Is it the correct approach?
        # assert registry.registerProvider(metadata)
        registry.registerProvider(metadata)

    def initGui(self):
        self.dip = DataItemProvider()
        QgsApplication.instance().dataItemProviderRegistry().addProvider(self.dip)

    def unload(self):
        QgsApplication.instance().dataItemProviderRegistry().removeProvider(self.dip)
