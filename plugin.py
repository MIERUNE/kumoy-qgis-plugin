import os
import webbrowser

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsLayerTreeLayer,
    QgsMessageLog,
    QgsProject,
    QgsProviderRegistry,
    QgsRasterLayer,
    QgsVectorLayer,
)
from qgis.gui import QgisInterface, QgsGui
from qgis.PyQt.QtWidgets import QAction, QMenu, QMessageBox

from . import i18n
from .ui.error_handler import handle_api_error
from .kumoy import api
from .kumoy.api.error import AppError, format_api_error
from .kumoy.constants import (
    DATA_PROVIDER_KEY,
    DOCUMENTATION_URL,
    LOG_CATEGORY,
    PLUGIN_NAME,
    RASTER_DATA_PROVIDER_KEY,
)
from .ui.project_save_handler import handle_project_saved
from .kumoy.provider.dataprovider_metadata import KumoyProviderMetadata
from .kumoy.provider.raster_dataprovider_metadata import KumoyRasterProviderMetadata
from .plugin_version import is_plugin_version_compatible, read_plugin_version
from .processing.close_all_processing_dialogs import close_all_processing_dialogs
from .processing.provider import KumoyProcessingProvider
from .pyqt_version import Q_MESSAGEBOX_STD_BUTTON
from .kumoy.settings_manager import (
    get_settings,
    reset_settings,
    store_setting,
)
from .ui.browser.gui_provider import KumoyDataItemGuiProvider
from .ui.browser.root import DataItemProvider
from .ui.icons import MAIN_ICON
from .ui.layers.convert_raster import on_convert_raster_to_kumoy_clicked
from .ui.layers.convert_vector import on_convert_to_kumoy_clicked
from .ui.layers.indicators import update_kumoy_indicator


class KumoyPlugin:
    def __init__(self, iface: QgisInterface):
        self.iface = iface
        self.win = self.iface.mainWindow()
        self.plugin_dir = os.path.dirname(__file__)

        # Initialize translation
        self.init_translation()

        registry = QgsProviderRegistry.instance()
        metadata = KumoyProviderMetadata()
        registry.registerProvider(metadata)  # needs reopen QGIS to unregister
        # ラスタは別プロバイダキーで登録する（ベクタと責務を分離）
        registry.registerProvider(KumoyRasterProviderMetadata())

        # Initialize processing provider
        self.processing_provider = None

        self.convert_action = None

        # Initialize menu actions
        self.kumoy_menu = None
        self.reset_plugin_settings = None
        self.logout_action = None
        self.help_action = None
        self.data_item_gui_provider = None

    def init_translation(self):
        """Load translations for the current QGIS locale."""
        i18n.load(QgsApplication.instance().locale())

    def on_reset_settings(self):
        """Handle reset settings action"""
        reply = QMessageBox.question(
            self.win,
            i18n.tr("Reset Plugin Settings"),
            i18n.tr(
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
                    i18n.tr("Reset Plugin Settings"),
                    i18n.tr(
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

            self._refresh_browser_panel()

            QMessageBox.information(
                self.win,
                i18n.tr("Reset Plugin Settings"),
                i18n.tr("Plugin settings have been reset successfully."),
            )

    def on_logout(self):
        """Handle logout action"""
        if QgsProject.instance().isDirty():
            confirmed = QMessageBox.question(
                self.win,
                i18n.tr("Logout"),
                i18n.tr(
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
        store_setting("session_token", "")
        store_setting("user_info", "")
        store_setting("selected_project_id", "")
        store_setting("selected_organization_id", "")

        QgsMessageLog.logMessage("Logged out via menu", PLUGIN_NAME, Qgis.Info)
        QMessageBox.information(
            self.win,
            i18n.tr("Logout"),
            i18n.tr("You have been logged out from Kumoy."),
        )

        self._refresh_browser_panel()

    def show_layer_context_menu(self, menu: QMenu):
        """Add custom action to layer context menu"""
        # Get the current layer from the layer tree view
        layer_tree_view = self.iface.layerTreeView()
        current_node = layer_tree_view.currentNode()

        if not isinstance(current_node, QgsLayerTreeLayer):
            return

        layer = current_node.layer()

        if not layer or not layer.isValid():
            return

        provider = layer.dataProvider()
        if not provider:
            return

        if isinstance(layer, QgsVectorLayer):
            if provider.name() == DATA_PROVIDER_KEY:
                # Kumoyレイヤーの場合: 同期アクションを追加
                sync_action = QAction(MAIN_ICON, i18n.tr("Sync Data"), menu)
                sync_action.setIconVisibleInMenu(True)
                sync_action.triggered.connect(lambda: self._sync_kumoy_layer(layer))
                if layer.isEditable():
                    sync_action.setEnabled(False)
                self._insert_action_after_last_separator(menu, sync_action)
                return
        elif isinstance(layer, QgsRasterLayer):
            # Kumoyラスタは immutable なので同期アクションは無い。
            if provider.name() == RASTER_DATA_PROVIDER_KEY:
                return
        else:
            return

        # Get current project id and role from browser root collection
        root = self.dip.root_collection
        if not root.project_data:
            return

        # Role must be ADMIN or OWNER
        if root.project_data.role not in ["ADMIN", "OWNER"]:
            return

        # Create and add convert action
        if isinstance(layer, QgsVectorLayer):
            convert_action = QAction(
                MAIN_ICON, i18n.tr("Convert to Kumoy Vector"), menu
            )
            convert_action.triggered.connect(
                lambda: on_convert_to_kumoy_clicked(layer, root.project_data.id)
            )
            # 編集中(未保存)のベクタは変換不可
            if layer.isModified():
                convert_action.setEnabled(False)
        else:
            convert_action = QAction(
                MAIN_ICON, i18n.tr("Convert to Kumoy Raster"), menu
            )
            convert_action.triggered.connect(
                lambda: on_convert_raster_to_kumoy_clicked(layer, root.project_data.id)
            )
        convert_action.setIconVisibleInMenu(True)
        self._insert_action_after_last_separator(menu, convert_action)

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
                i18n.tr("Sync Error"),
                str(e),
            )
            return
        # provider.fields() がカラム順・追加・削除で変わっている可能性があるので、
        # レイヤー側のフィールドキャッシュを更新し、属性テーブル等にも変更を通知する
        layer.updateFields()
        layer.dataChanged.emit()
        layer.triggerRepaint()
        self.iface.mapCanvas().refresh()

    def check_kumoy_project_on_load(self) -> None:
        """Check if the loaded project is associated with the current Kumoy project"""
        project = QgsProject.instance()

        # Get styled map ID from custom variables
        custom_vars = project.customVariables()
        styled_map_id = custom_vars.get("kumoy_map_id")

        # No need to check if not a kumoy map
        if not styled_map_id:
            return

        # Validate that the map belongs to current project
        try:
            styled_map_detail = api.styledmap.get_styled_map(styled_map_id)
            settings = get_settings()

            if settings.selected_project_id != styled_map_detail.projectId:
                QMessageBox.critical(
                    None,
                    i18n.tr("Wrong Project"),
                    i18n.tr(
                        "This map belongs to a different Kumoy project. "
                        "Please switch to the correct project."
                    ),
                )
                QgsProject.instance().clear()
                return
        except Exception as e:
            handle_api_error(e, parent=None, log_prefix=i18n.tr("Error loading map"))
            QgsProject.instance().clear()
            return

    def check_plugin_version(self):
        """Check if the plugin version is compatible with the minimum required version"""
        try:
            params = api.public.get_params()
        except AppError as e:
            error_text = format_api_error(e)
            QgsMessageLog.logMessage(
                f"Error: {error_text}", LOG_CATEGORY, Qgis.Critical
            )
            QMessageBox.critical(
                None,
                i18n.tr("Error"),
                i18n.tr(
                    "Unable to connect to the server or retrieve plugin version information.\n\n"
                    "Details: {}"
                ).format(error_text),
            )
            return
        except Exception as e:
            error_text = format_api_error(e)
            QgsMessageLog.logMessage(
                f"Error: {error_text}", LOG_CATEGORY, Qgis.Critical
            )
            QMessageBox.critical(
                None,
                i18n.tr("Error"),
                i18n.tr("An error occurred: {}").format(error_text),
            )
            return

        min_qgisplugin_version = params.minQgisPluginVersion
        if min_qgisplugin_version is not None and not is_plugin_version_compatible(
            read_plugin_version(), min_qgisplugin_version
        ):
            QMessageBox.critical(
                None,
                i18n.tr("Plugin Version Error"),
                i18n.tr(
                    "Please update the Kumoy plugin.\nMinimum required version: {}"
                ).format(min_qgisplugin_version),
            )
            # Force logout to prevent potential issues with incompatible versions
            # Clear stored settings
            store_setting("session_token", "")
            store_setting("user_info", "")
            store_setting("selected_project_id", "")
            store_setting("selected_organization_id", "")

            QgsMessageLog.logMessage(
                "Logged out due to incompatible plugin version",
                PLUGIN_NAME,
                Qgis.Info,
            )

            # Refresh browser panel
            registry = QgsApplication.instance().dataItemProviderRegistry()
            registry.removeProvider(self.dip)
            self.dip = DataItemProvider()
            registry.addProvider(self.dip)

    def _refresh_browser_panel(self):
        """Kumoy ルートアイテム配下の子要素を depopulate して再構築させる。
        ログアウトやプラグイン設定リセット時の表示更新に使う。
        （セッション切れ時の自動リフレッシュは `ui/error_handler.py` 側が
        registry 経由で同じことをする。）"""
        if self.dip is None or self.dip.root_collection is None:
            return
        self.dip.root_collection.refresh()

    def initGui(self):
        self.dip = DataItemProvider()
        QgsApplication.instance().dataItemProviderRegistry().addProvider(self.dip)

        self.data_item_gui_provider = KumoyDataItemGuiProvider()
        QgsGui.dataItemGuiProviderRegistry().addProvider(self.data_item_gui_provider)

        # Register processing provider
        self.processing_provider = KumoyProcessingProvider()
        QgsApplication.processingRegistry().addProvider(self.processing_provider)

        # Connect to layer tree context menu
        self.iface.layerTreeView().contextMenuAboutToShow.connect(
            self.show_layer_context_menu
        )

        # Connect project loaded signal
        self.iface.projectRead.connect(self.check_kumoy_project_on_load)

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

        # Create Plugin Menu
        self.kumoy_menu = QMenu(PLUGIN_NAME, self.win)
        self.kumoy_menu.setIcon(MAIN_ICON)
        self.iface.pluginMenu().addMenu(self.kumoy_menu)

        # Add menu action for logout
        self.logout_action = QAction(i18n.tr("Logout"), self.win)
        self.logout_action.triggered.connect(self.on_logout)
        self.kumoy_menu.addAction(self.logout_action)

        # Add menu action for resetting settings
        self.reset_plugin_settings = QAction(i18n.tr("Reset Plugin Settings"), self.win)
        self.reset_plugin_settings.triggered.connect(self.on_reset_settings)
        self.kumoy_menu.addAction(self.reset_plugin_settings)

        # Add menu action for help/documentation
        self.help_action = QAction(i18n.tr("Help"), self.win)
        self.help_action.triggered.connect(lambda: webbrowser.open(DOCUMENTATION_URL))
        self.kumoy_menu.addAction(self.help_action)

        # Connect to plugin menu aboutToShow to update logout action visibility
        self.iface.pluginMenu().aboutToShow.connect(
            self.update_logout_action_visibility
        )
        self.update_logout_action_visibility()

        # Check plugin version compatibility
        self.check_plugin_version()

    def update_logout_action_visibility(self):
        # MEMO: メニューバーを開くたびに実行されるので重たい処理を実装してはいけない
        is_logged_in = bool(api.config.get_settings().session_token)
        self.logout_action.setVisible(is_logged_in)

    def unload(self):
        # Remove menu actions
        if self.kumoy_menu is not None:
            self.iface.pluginMenu().removeAction(self.kumoy_menu.menuAction())
            self.kumoy_menu.deleteLater()
            self.kumoy_menu = None

        QgsApplication.instance().dataItemProviderRegistry().removeProvider(self.dip)

        if self.data_item_gui_provider:
            QgsGui.dataItemGuiProviderRegistry().removeProvider(
                self.data_item_gui_provider
            )

        # Unregister processing provider
        close_all_processing_dialogs()
        if self.processing_provider:
            QgsApplication.processingRegistry().removeProvider(self.processing_provider)

        # Disconnect signals
        try:
            self.iface.layerTreeView().contextMenuAboutToShow.disconnect(
                self.show_layer_context_menu
            )
            self.iface.projectRead.disconnect(self.check_kumoy_project_on_load)
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
