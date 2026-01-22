import os
from functools import partial

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsLayerTreeLayer,
    QgsMessageLog,
    QgsProject,
    QgsProviderRegistry,
    QgsVectorLayer,
)
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QCoreApplication, QTranslator
from qgis.PyQt.QtWidgets import QAction, QMenu, QMessageBox

from .kumoy.api.config import get_settings
from .kumoy.constants import DATA_PROVIDER_KEY, PLUGIN_NAME
from .kumoy.local_cache.map import handle_project_saved
from .kumoy.provider.dataprovider_metadata import KumoyProviderMetadata
from .processing.close_all_processing_dialogs import close_all_processing_dialogs
from .processing.provider import KumoyProcessingProvider
from .pyqt_version import Q_MESSAGEBOX_STD_BUTTON
from .sentry import init_sentry
from .settings_manager import reset_settings, store_setting
from .ui.browser.root import DataItemProvider
from .ui.icons import MAIN_ICON
from .ui.layers.convert_vector import on_convert_to_kumoy_clicked
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
        registry.registerProvider(metadata)  # needs reopen QGIS to unregister

        # Initialize processing provider
        self.processing_provider = None

        self.convert_action = None

        # Initialize menu actions
        self.reset_plugin_settings = None
        self.logout_action = None

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
            close_all_processing_dialogs()
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

    def on_logout(self):
        """Handle logout action"""
        if QgsProject.instance().isDirty():
            confirmed = QMessageBox.question(
                self.win,
                self.tr("Logout"),
                self.tr(
                    "You have unsaved changes. "
                    "Logging out will clear your current project. Continue?"
                ),
                Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
                Q_MESSAGEBOX_STD_BUTTON.No,
            )

            if confirmed != Q_MESSAGEBOX_STD_BUTTON.Yes:
                return

        QgsProject.instance().clear()

        close_all_processing_dialogs()

        # Clear stored settings
        store_setting("id_token", "")
        store_setting("refresh_token", "")
        store_setting("user_info", "")
        store_setting("selected_project_id", "")
        store_setting("selected_organization_id", "")

        QgsMessageLog.logMessage("Logged out via menu", PLUGIN_NAME, Qgis.Info)
        QMessageBox.information(
            self.win,
            self.tr("Logout"),
            self.tr("You have been logged out from Kumoy."),
        )

        # Refresh browser panel
        registry = QgsApplication.instance().dataItemProviderRegistry()
        registry.removeProvider(self.dip)
        self.dip = DataItemProvider()
        registry.addProvider(self.dip)

    def show_layer_context_menu(self, menu: QMenu):
        """Add custom action to layer context menu"""
        # Get the current layer from the layer tree view
        layer_tree_view = self.iface.layerTreeView()
        current_node = layer_tree_view.currentNode()

        if not isinstance(current_node, QgsLayerTreeLayer):
            return

        layer = current_node.layer()

        if not layer or not layer.isValid() or not isinstance(layer, QgsVectorLayer):
            return

        provider = layer.dataProvider()
        if not provider or provider.name() == DATA_PROVIDER_KEY:
            return

        # Create and add convert action
        action = QAction(MAIN_ICON, self.tr("Convert to Kumoy Vector"), menu)
        action.triggered.connect(partial(on_convert_to_kumoy_clicked, layer))
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

        # Add menu action for logout
        self.logout_action = QAction(self.tr("Logout"), self.win)
        self.logout_action.triggered.connect(self.on_logout)
        self.iface.addPluginToMenu(PLUGIN_NAME, self.logout_action)

        # Add menu action for resetting settings
        self.reset_plugin_settings = QAction(self.tr("Reset Plugin Settings"), self.win)
        self.reset_plugin_settings.triggered.connect(self.on_reset_settings)
        self.iface.addPluginToMenu(PLUGIN_NAME, self.reset_plugin_settings)

        # Connect to plugin menu aboutToShow to update logout action visibility
        self.iface.pluginMenu().aboutToShow.connect(
            self.update_logout_action_visibility
        )
        self.update_logout_action_visibility()

    def update_logout_action_visibility(self):
        # MEMO: メニューバーを開くたびに実行されるので重たい処理を実装してはいけない
        is_logged_in = bool(get_settings().id_token)
        self.logout_action.setVisible(is_logged_in)

    def unload(self):
        # Remove menu actions
        if self.logout_action:
            self.iface.removePluginMenu(PLUGIN_NAME, self.logout_action)
        if self.reset_plugin_settings:
            self.iface.removePluginMenu(PLUGIN_NAME, self.reset_plugin_settings)

        # Remove translator
        if self.translator:
            QCoreApplication.removeTranslator(self.translator)

        QgsApplication.instance().dataItemProviderRegistry().removeProvider(self.dip)

        # Unregister processing provider
        close_all_processing_dialogs()
        if self.processing_provider:
            QgsApplication.processingRegistry().removeProvider(self.processing_provider)

        # Disconnect signals
        try:
            self.iface.layerTreeView().contextMenuAboutToShow.disconnect(
                self.show_layer_context_menu
            )
            QgsProject.instance().projectSaved.disconnect(handle_project_saved)
            QgsProject.instance().layersAdded.disconnect(update_kumoy_indicator)
            QgsProject.instance().layerTreeRoot().removedChildren.disconnect(
                update_kumoy_indicator
            )
            QgsProject.instance().layerTreeRoot().addedChildren.disconnect(
                update_kumoy_indicator
            )
            self.iface.pluginMenu().aboutToShow.disconnect(
                self.update_logout_action_visibility
            )
        except TypeError:
            pass
