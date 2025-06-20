from typing import Dict, List, Tuple

from PyQt5.QtCore import QCoreApplication
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
)
from qgis.core import (
    QgsMapLayer,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)

from qgishub.qgisproject.check import CompatibilityChecker


class MapLibreCompatibilityDialog(QDialog):
    """Dialog to show MapLibre compatibility information for project layers"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("MapLibre Compatibility Check"))
        self.setMinimumSize(500, 200)
        self._setup_ui()
        self._analyze_and_display()

    def tr(self, message):
        """Get the translation for a string using Qt translation API"""
        return QCoreApplication.translate("MapLibreCompatibilityDialog", message)

    def _setup_ui(self):
        """Setup the dialog UI"""
        layout = QVBoxLayout()

        # Create label for content
        self.content_label = QLabel()
        self.content_label.setTextFormat(1)  # RichText format
        self.content_label.setWordWrap(True)

        # Add scroll area in case content is long
        scroll_area = QScrollArea()
        scroll_area.setWidget(self.content_label)
        scroll_area.setWidgetResizable(True)

        layout.addWidget(scroll_area)

        # Add buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

    def _analyze_and_display(self):
        """Analyze layers and display compatibility information"""
        compatible_layers, incompatible_layers = (
            self._analyze_layer_maplibre_compatibility()
        )

        if not compatible_layers and not incompatible_layers:
            # No layers found - show info message and close dialog
            QMessageBox.information(
                self.parent(),
                self.tr("Layer Compatibility"),
                self.tr("No layers found in the current project."),
            )
            # Set result to accepted since this is not an error
            self.accept()
            return

        # Create HTML message with colored text
        html_parts = []
        html_parts.append(
            f"<b>{self.tr('Layer compatibility analysis for MapLibre:')}</b><br><br>"
        )

        if compatible_layers:
            html_parts.append(f"<b>{self.tr('MapLibre Compatible Layers:')}</b><br>")
            for layer in compatible_layers:
                html_parts.append(f"<span style='color: green;'>✓ {layer}</span><br>")
            html_parts.append("<br>")

        if incompatible_layers:
            html_parts.append(f"<b>{self.tr('MapLibre Incompatible Layers:')}</b><br>")
            for layer in incompatible_layers:
                html_parts.append(f"<span style='color: red;'>✗ {layer}</span><br>")
            html_parts.append("<br>")

        html_parts.append(f"<b>{self.tr('Note:')}</b><br>")
        html_parts.append(
            f"• {self.tr('Web display: Only MapLibre Compatible Layers will be shown')}<br>"
        )
        html_parts.append(
            f"• {self.tr('Local QGIS: All layers will be fully restored with complete configuration')}"
        )

        self.content_label.setText("".join(html_parts))

    def _analyze_layer_maplibre_compatibility(self) -> Tuple[List[str], List[str]]:
        """
        Analyze current QGIS project layers for MapLibre compatibility.

        Returns:
            Tuple of (compatible_layers, incompatible_layers) where each is a list
            of strings in the format "layer_name (provider_type)"
        """
        project = QgsProject.instance()
        layers: Dict[str, QgsMapLayer] = project.mapLayers()

        compatible_layers = []
        incompatible_layers = []

        for map_layer in layers.values():
            layer_name = map_layer.name()
            provider_type = map_layer.dataProvider().name()
            layer_info = f"{layer_name} ({provider_type})"

            # Check layer compatibility based on type
            if isinstance(map_layer, QgsVectorLayer):
                is_compatible, reason = CompatibilityChecker.vector().check(map_layer)
            elif isinstance(map_layer, QgsRasterLayer):
                is_compatible, reason = CompatibilityChecker.raster().check(map_layer)
            else:
                is_compatible, reason = False, " - unsupported layer type"

            if is_compatible:
                compatible_layers.append(layer_info)
            else:
                incompatible_layers.append(layer_info + reason)

        return compatible_layers, incompatible_layers
