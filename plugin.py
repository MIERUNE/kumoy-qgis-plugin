import os

from qgis.core import QgsApplication, QgsProject, QgsProviderRegistry, QgsVectorLayer
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QCoreApplication, QTranslator
from qgis.PyQt.QtWidgets import QAction, QMenu, QMessageBox

from .kumoy.api.config import get_settings
from .kumoy.constants import DATA_PROVIDER_KEY, PLUGIN_NAME
from .kumoy.local_cache.map import handle_project_saved
from .kumoy.provider.dataprovider_metadata import KumoyProviderMetadata
from .processing.provider import KumoyProcessingProvider
from .pyqt_version import Q_MESSAGEBOX_STD_BUTTON
from .sentry import init_sentry
from .settings_manager import reset_settings

from .ui.browser.root import DataItemProvider
from .ui.icons import MAIN_ICON
from .ui.layers.convert_vector import convert_layer_to_kumoy
from .ui.layers.indicators import update_kumoy_indicator


class KumoyPlugin:
    def __init__(self, iface: QgisInterface):
        self.iface = iface
        self.win = self.iface.mainWindow()
        self.plugin_dir = os.path.dirname(__file__)

        # Initialize translation
        self.translator = None
        self.init_translation()

        registry = QgsProviderRegistry.instance()
        metadata = KumoyProviderMetadata()
        # FIXME: It is not possible to remove unregister a provider
        # Is it the correct approach?
        # assert registry.registerProvider(metadata)
        registry.registerProvider(metadata)

        # Initialize processing provider
        self.processing_provider = None
        self.convert_action = None

        # Initialize menu action
        self.reset_plugin_settings = None

        if get_settings().id_token:
            init_sentry()

    def init_translation(self):
        """Initialize translation for the plugin"""
        locale = QgsApplication.instance().locale()
        locale_path = os.path.join(self.plugin_dir, "i18n", f"kumoy_{locale}.qm")

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

    def tr(self, message):
        """Get the translation for a string using Qt translation API"""
        return QCoreApplication.translate(PLUGIN_NAME, message)

    def on_reset_settings(self):
        """Handle reset settings action"""
        reply = QMessageBox.question(
            self.win,
            self.tr("Reset Plugin Settings"),
            self.tr(
                'Are you sure you want to reset all settings for the "Kumoy" plugin? '
                "This will clear your current project."
            ),
            Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
            Q_MESSAGEBOX_STD_BUTTON.No,
        )

        if reply == Q_MESSAGEBOX_STD_BUTTON.Yes:
            if QgsProject.instance().isDirty():
                confirmed = QMessageBox.question(
                    self.win,
                    self.tr("Reset Plugin Settings"),
                    self.tr(
                        "You have unsaved changes. "
                        "Resetting settings will clear your current project. Continue?"
                    ),
                    Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
                    Q_MESSAGEBOX_STD_BUTTON.No,
                )

                if confirmed != Q_MESSAGEBOX_STD_BUTTON.Yes:
                    return

            QgsProject.instance().clear()
            reset_settings()

            # Refresh browser panel
            registry = QgsApplication.instance().dataItemProviderRegistry()
            registry.removeProvider(self.dip)
            self.dip = DataItemProvider()
            registry.addProvider(self.dip)

            QMessageBox.information(
                self.win,
                self.tr("Reset Plugin Settings"),
                self.tr("Plugin settings have been reset successfully."),
            )

    def show_layer_context_menu(self, menu: QMenu):
        """Add custom action to layer context menu"""
        # Get the current layer from the layer tree view
        layer_tree_view = self.iface.layerTreeView()
        current_node = layer_tree_view.currentNode()

        if not current_node or not hasattr(current_node, "layer"):
            return

        layer = current_node.layer()

        if not isinstance(layer, QgsVectorLayer):
            return
        if layer.dataProvider().name() == DATA_PROVIDER_KEY:
            return

        # Create and add convert action
        action = QAction(MAIN_ICON, self.tr("Convert to Kumoy Vector"), menu)
        action.triggered.connect(lambda: convert_layer_to_kumoy(layer))
        menu.addSeparator()
        menu.addAction(action)

    def initGui(self):
        self.dip = DataItemProvider()
        QgsApplication.instance().dataItemProviderRegistry().addProvider(self.dip)

        # Register processing provider
        self.processing_provider = KumoyProcessingProvider()
        QgsApplication.processingRegistry().addProvider(self.processing_provider)

        # Connect to layer tree context menu
        self.iface.layerTreeView().contextMenuAboutToShow.connect(
            self.show_layer_context_menu
        )

        # Connect project saved signal
        QgsProject.instance().projectSaved.connect(handle_project_saved)

        # Connect indicator setting signals on map loaded and layer tree changes
        QgsProject.instance().layerTreeRoot().removedChildren.connect(
            update_kumoy_indicator
        )
        QgsProject.instance().layerTreeRoot().addedChildren.connect(
            update_kumoy_indicator
        )
        QgsProject.instance().layersAdded.connect(update_kumoy_indicator)

        # Add menu action for resetting settings
        self.reset_plugin_settings = QAction(self.tr("Reset Plugin Settings"), self.win)
        self.reset_plugin_settings.triggered.connect(self.on_reset_settings)
        self.iface.addPluginToMenu(PLUGIN_NAME, self.reset_plugin_settings)

    def unload(self):
        # Disconnect layer tree context menu
        try:
            self.iface.layerTreeView().contextMenuAboutToShow.disconnect(
                self.show_layer_context_menu
            )
        except TypeError:
            pass

        # Remove menu action
        if self.reset_plugin_settings:
            self.iface.removePluginMenu(PLUGIN_NAME, self.reset_plugin_settings)

        # Remove translator
        if self.translator:
            QCoreApplication.removeTranslator(self.translator)

        QgsApplication.instance().dataItemProviderRegistry().removeProvider(self.dip)

        # Unregister processing provider
        if self.processing_provider:
            QgsApplication.processingRegistry().removeProvider(self.processing_provider)

        # Disconnect signals
        try:
            QgsProject.instance().projectSaved.disconnect(handle_project_saved)
            QgsProject.instance().layersAdded.disconnect(update_kumoy_indicator)
            QgsProject.instance().layerTreeRoot().removedChildren.disconnect(
                update_kumoy_indicator
            )
            QgsProject.instance().layerTreeRoot().addedChildren.disconnect(
                update_kumoy_indicator
            )
        except TypeError:
            pass
