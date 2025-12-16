import os

from qgis.core import QgsApplication, QgsProviderRegistry, QgsProject
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QCoreApplication, QTranslator
from qgis.PyQt.QtWidgets import QAction, QMessageBox

from .pyqt_version import Q_MESSAGEBOX_STD_BUTTON
from .processing.provider import KumoyProcessingProvider
from .sentry import init_sentry
from .kumoy.api.config import get_settings
from .kumoy.constants import PLUGIN_NAME
from .kumoy.provider.dataprovider_metadata import KumoyProviderMetadata
from .ui.browser.root import DataItemProvider
from .settings_manager import reset_settings


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

            QMessageBox.information(
                self.win,
                self.tr("Reset Plugin Settings"),
                self.tr("Plugin settings have been reset successfully."),
            )

    def initGui(self):
        self.dip = DataItemProvider()
        QgsApplication.instance().dataItemProviderRegistry().addProvider(self.dip)

        # Register processing provider
        self.processing_provider = KumoyProcessingProvider()
        QgsApplication.processingRegistry().addProvider(self.processing_provider)

        # Add menu action for resetting settings
        self.reset_plugin_settings = QAction(self.tr("Reset Plugin Settings"), self.win)
        self.reset_plugin_settings.triggered.connect(self.on_reset_settings)
        self.iface.addPluginToMenu(PLUGIN_NAME, self.reset_plugin_settings)

    def unload(self):
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
