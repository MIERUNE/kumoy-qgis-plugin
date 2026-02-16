import os

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
from .settings_manager import (
    get_settings as get_kumoy_settings,
)
from .settings_manager import (
    reset_settings,
    store_setting,
)
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
        return QCoreApplication.translate("KumoyPlugin", message)

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
        if not provider:
            return

        if provider.name() == DATA_PROVIDER_KEY:
            # Kumoyレイヤーの場合: 同期アクションを追加
            sync_action = QAction(MAIN_ICON, self.tr("Sync Data"), menu)
            sync_action.triggered.connect(lambda: self._sync_kumoy_layer(layer))
            if layer.isEditable():
                sync_action.setEnabled(False)
            self._insert_action_after_last_separator(menu, sync_action)
            return

        # Get current project id and role from browser root collection
        root = self.dip.root_collection
        if not root.project_data:
            return

        # Role must be ADMIN or OWNER
        if root.project_data.role not in ["ADMIN", "OWNER"]:
            return

        # Create and add convert action
        action = QAction(MAIN_ICON, self.tr("Convert to Kumoy Vector"), menu)
        action.triggered.connect(
            lambda: on_convert_to_kumoy_clicked(layer, root.project_data.id)
        )
        self._insert_action_after_last_separator(menu, action)

    def _insert_action_after_last_separator(self, menu: QMenu, action: QAction):
        """Insert an action after the last separator in the menu."""
        actions = menu.actions()
        last_separator = None
        for a in actions:
            if a.isSeparator():
                last_separator = a

        if last_separator:
            index = actions.index(last_separator)
            if index + 1 < len(actions):
                menu.insertAction(actions[index + 1], action)
                menu.insertSeparator(actions[index + 1])
            else:
                menu.addAction(action)
                menu.addSeparator()
        else:
            menu.addSeparator()
            menu.addAction(action)

    def _sync_kumoy_layer(self, layer: QgsVectorLayer):
        """Sync a Kumoy vector layer with the latest server data"""
        provider = layer.dataProvider()
        try:
            provider._reload_vector()
        except Exception as e:
            QMessageBox.warning(
                self.win,
                self.tr("Sync Error"),
                str(e),
            )
            return
        layer.triggerRepaint()
        self.iface.mapCanvas().refresh()

    def _connect_sync_on_editing_started(self, layers):
        """Kumoy Vectorレイヤーの編集開始時にsyncを実行するようシグナルを接続する"""
        for layer in layers:
            if not isinstance(layer, QgsVectorLayer):
                continue
            provider = layer.dataProvider()
            if provider and provider.name() == DATA_PROVIDER_KEY:
                layer.beforeEditingStarted.connect(
                    lambda _layer=layer: self._sync_kumoy_layer(_layer)
                )

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
        QgsProject.instance().layersAdded.connect(self._connect_sync_on_editing_started)

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
            QgsProject.instance().layersAdded.disconnect(
                self._connect_sync_on_editing_started
            )
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
