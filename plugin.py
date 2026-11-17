import webbrowser

from qgis.core import (
    QgsApplication,
    QgsLayerTreeLayer,
    QgsProject,
    QgsProviderRegistry,
    QgsRasterLayer,
    QgsVectorLayer,
)
from qgis.gui import QgisInterface, QgsGui
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QAction, QMenu

from . import i18n
from .kumoy import session
from .kumoy.api.models import is_editor
from .kumoy.constants import DATA_PROVIDER_KEY, DOCUMENTATION_URL, PLUGIN_NAME
from .kumoy.provider.dataprovider_metadata import KumoyProviderMetadata
from .kumoy.provider.raster_dataprovider_metadata import KumoyRasterProviderMetadata
from .processing.close_all_processing_dialogs import close_all_processing_dialogs
from .processing.provider import KumoyProcessingProvider
from .ui import account_actions
from .ui.browser.gui_provider import KumoyDataItemGuiProvider
from .ui.browser.root import DataItemProvider, current_project
from .ui.dialog_login import open_login_dialog
from .ui.icons import MAIN_ICON
from .ui.layers.convert import on_convert_layer_clicked
from .ui.layers.indicators import update_kumoy_indicator

try:
    # INTEGRATION(C): maps open/save through the Kumoy project storage
    from .ui import project_storage
except ImportError:
    project_storage = None


class KumoyPlugin:
    def __init__(self, iface: QgisInterface):
        self.iface = iface
        self.win = self.iface.mainWindow()
        i18n.load(QgsApplication.instance().locale())

        registry = QgsProviderRegistry.instance()
        registry.registerProvider(
            KumoyProviderMetadata()
        )  # needs a restart to unregister
        registry.registerProvider(KumoyRasterProviderMetadata())

        self.dip = None
        self.data_item_gui_provider = None
        self.processing_provider = None
        self.kumoy_menu = None
        self.login_action = None
        self.logout_action = None

    def initGui(self):
        # No network and no dialog here: QGIS is still starting up
        self.dip = DataItemProvider()
        QgsApplication.instance().dataItemProviderRegistry().addProvider(self.dip)

        self.data_item_gui_provider = KumoyDataItemGuiProvider()
        QgsGui.dataItemGuiProviderRegistry().addProvider(self.data_item_gui_provider)

        self.processing_provider = KumoyProcessingProvider()
        QgsApplication.processingRegistry().addProvider(self.processing_provider)

        if project_storage is not None:
            project_storage.register()

        self.iface.layerTreeView().contextMenuAboutToShow.connect(
            self.show_layer_context_menu
        )

        project = QgsProject.instance()
        project.layerTreeRoot().removedChildren.connect(update_kumoy_indicator)
        project.layerTreeRoot().addedChildren.connect(update_kumoy_indicator)
        project.layersAdded.connect(update_kumoy_indicator)

        self.kumoy_menu = QMenu(PLUGIN_NAME, self.win)
        self.kumoy_menu.setIcon(MAIN_ICON)
        self.iface.pluginMenu().addMenu(self.kumoy_menu)

        self.login_action = QAction(i18n.tr("Log In…"), self.win)
        self.login_action.triggered.connect(open_login_dialog)
        self.kumoy_menu.addAction(self.login_action)

        self.logout_action = QAction(i18n.tr("Logout"), self.win)
        self.logout_action.triggered.connect(lambda: account_actions.logout(self.win))
        self.kumoy_menu.addAction(self.logout_action)

        reset_action = QAction(i18n.tr("Reset Plugin Settings"), self.kumoy_menu)
        reset_action.triggered.connect(lambda: account_actions.reset_settings(self.win))
        self.kumoy_menu.addAction(reset_action)

        help_action = QAction(i18n.tr("Help"), self.kumoy_menu)
        help_action.triggered.connect(lambda: webbrowser.open(DOCUMENTATION_URL))
        self.kumoy_menu.addAction(help_action)

        self.iface.pluginMenu().aboutToShow.connect(self.update_menu)
        self.update_menu()

        # Loading the login may prompt for the master password: wait until
        # QGIS has finished starting (see account_actions.start_session)
        if self.win.isVisible():  # enabled later from the Plugin Manager
            QTimer.singleShot(0, account_actions.start_session)
        else:
            self.iface.initializationCompleted.connect(account_actions.start_session)

    def update_menu(self):
        # Runs every time the Plugins menu opens: keep it cheap
        logged_in = session.is_logged_in()
        self.login_action.setVisible(not logged_in)
        self.logout_action.setVisible(logged_in)

    def show_layer_context_menu(self, menu: QMenu):
        node = self.iface.layerTreeView().currentNode()
        if not isinstance(node, QgsLayerTreeLayer):
            return
        layer = node.layer()
        if not layer or not layer.isValid() or not layer.dataProvider():
            return
        provider = layer.dataProvider()

        if isinstance(layer, QgsVectorLayer):
            if provider.name() == DATA_PROVIDER_KEY:
                sync_action = QAction(MAIN_ICON, i18n.tr("Sync Data"), menu)
                sync_action.setIconVisibleInMenu(True)
                # Area A's provider syncs in the background
                sync_action.triggered.connect(lambda: provider.sync())
                sync_action.setEnabled(not layer.isEditable())
                self._insert_action_after_last_separator(menu, sync_action)
                return
            label = i18n.tr("Convert to Kumoy Vector")
        elif isinstance(layer, QgsRasterLayer):
            # Kumoy rasters are immutable: no sync. Conversion reads the
            # source with GDAL, so remote rasters (WMS/XYZ/...) are excluded
            if provider.name() != "gdal":
                return
            label = i18n.tr("Convert to Kumoy Raster")
        else:
            return

        # The role comes from the project the Browser loaded in the
        # background; until then the action is not offered
        project = current_project()
        if not session.is_logged_in() or project is None or not is_editor(project.role):
            return
        convert_action = QAction(MAIN_ICON, label, menu)
        convert_action.setIconVisibleInMenu(True)
        if isinstance(layer, QgsVectorLayer) and layer.isModified():
            convert_action.setEnabled(False)  # unsaved edits would be lost
        project_id = project.id
        convert_action.triggered.connect(
            lambda: on_convert_layer_clicked(layer, project_id)
        )
        self._insert_action_after_last_separator(menu, convert_action)

    def _insert_action_after_last_separator(self, menu: QMenu, action: QAction):
        actions = menu.actions()
        separators = [i for i, a in enumerate(actions) if a.isSeparator()]
        if not separators:
            menu.addSeparator()
            menu.addAction(action)
            return
        index = separators[-1] + 1
        if index < len(actions):
            menu.insertAction(actions[index], action)
            menu.insertSeparator(actions[index])
        else:
            menu.addAction(action)
            menu.addSeparator()

    def unload(self):
        if self.kumoy_menu is not None:
            self.iface.pluginMenu().removeAction(self.kumoy_menu.menuAction())
            self.kumoy_menu.deleteLater()
            self.kumoy_menu = None

        if self.dip is not None:
            QgsApplication.instance().dataItemProviderRegistry().removeProvider(
                self.dip
            )
        if self.data_item_gui_provider is not None:
            QgsGui.dataItemGuiProviderRegistry().removeProvider(
                self.data_item_gui_provider
            )

        close_all_processing_dialogs()
        if self.processing_provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.processing_provider)

        if project_storage is not None:
            project_storage.unregister()

        project = QgsProject.instance()
        for signal, slot in (
            (
                self.iface.layerTreeView().contextMenuAboutToShow,
                self.show_layer_context_menu,
            ),
            (project.layersAdded, update_kumoy_indicator),
            (project.layerTreeRoot().removedChildren, update_kumoy_indicator),
            (project.layerTreeRoot().addedChildren, update_kumoy_indicator),
            (self.iface.pluginMenu().aboutToShow, self.update_menu),
            (self.iface.initializationCompleted, account_actions.start_session),
        ):
            try:
                signal.disconnect(slot)
            except TypeError:
                pass  # not connected
