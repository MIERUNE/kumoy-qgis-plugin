from abc import ABC, abstractmethod
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
    QgsSymbol,
    QgsSymbolLayer,
    QgsVectorLayer,
    QgsWkbTypes,
)


class LayerCompatibilityChecker(ABC):
    """Abstract base class for layer compatibility checking"""

    @abstractmethod
    def check(self, layer: QgsMapLayer) -> Tuple[bool, str]:
        """
        Check if a layer is compatible with MapLibre.

        Returns:
            Tuple of (is_compatible, reason_if_not_compatible)
        """
        pass


class GeometrySymbolChecker(ABC):
    """Abstract base class for geometry-specific symbol checking"""

    @abstractmethod
    def is_compatible_symbol_layer(self, symbol_layer) -> bool:
        """Check if a symbol layer is compatible for this geometry type"""
        pass

    @abstractmethod
    def get_error_message(self) -> str:
        """Get the error message for incompatible symbols of this geometry type"""
        pass


class PointSymbolChecker(GeometrySymbolChecker):
    """Symbol checker for point geometry"""

    def is_compatible_symbol_layer(self, symbol_layer: QgsSymbolLayer) -> bool:
        """Check if symbol layer is compatible with point geometry"""
        compatible_types = {"SimpleMarker"}
        return symbol_layer.layerType() in compatible_types

    def get_error_message(self) -> str:
        """Get error message for incompatible point symbols"""
        return " - unsupported point renderer"


class LineSymbolChecker(GeometrySymbolChecker):
    """Symbol checker for line geometry"""

    def is_compatible_symbol_layer(self, symbol_layer: QgsSymbolLayer) -> bool:
        """Check if symbol layer is compatible with line geometry"""
        compatible_types = {"SimpleLine"}
        return symbol_layer.layerType() in compatible_types

    def get_error_message(self) -> str:
        """Get error message for incompatible line symbols"""
        return " - unsupported line renderer"


class PolygonSymbolChecker(GeometrySymbolChecker):
    """Symbol checker for polygon geometry"""

    def is_compatible_symbol_layer(self, symbol_layer: QgsSymbolLayer) -> bool:
        """Check if symbol layer is compatible with polygon geometry"""
        compatible_types = {"SimpleFill"}
        return symbol_layer.layerType() in compatible_types

    def get_error_message(self) -> str:
        """Get error message for incompatible polygon symbols"""
        return " - unsupported polygon renderer"


class VectorLayerChecker(LayerCompatibilityChecker):
    """Compatibility checker for vector layers"""

    def __init__(self):
        # Initialize geometry-specific checkers
        self.geometry_checkers = {
            QgsWkbTypes.PointGeometry: PointSymbolChecker(),
            QgsWkbTypes.LineGeometry: LineSymbolChecker(),
            QgsWkbTypes.PolygonGeometry: PolygonSymbolChecker(),
        }

    @staticmethod
    def check(layer: QgsVectorLayer) -> Tuple[bool, str]:
        """Check vector layer compatibility based on provider and renderer"""
        # Create instance to use geometry checkers
        checker = VectorLayerChecker()
        return checker._check_layer(layer)

    def _check_layer(self, layer: QgsVectorLayer) -> Tuple[bool, str]:
        """Internal method to check layer compatibility"""
        provider_type = layer.dataProvider().name()

        if provider_type != "qgishub":
            return False, " - generic vector data not supported"

        # Get renderer and check type
        renderer = layer.renderer()
        if not renderer:
            return False, " - no renderer found"

        # Only single symbol renderers are supported for now
        renderer_type = renderer.type()
        if renderer_type != "singleSymbol":
            return False, f" - {renderer_type} renderer not supported"

        # Get symbol from single symbol renderer
        symbol: QgsSymbol = renderer.symbol()
        if not symbol:
            return False, " - no symbol found"

        # Get geometry-specific checker
        geometry_type = layer.geometryType()
        if geometry_type not in self.geometry_checkers:
            return False, " - unsupported geometry type"

        geometry_checker: GeometrySymbolChecker = self.geometry_checkers[geometry_type]
        symbol_layers = symbol.symbolLayers()

        # Check symbol layers using geometry-specific checker
        if symbol_layers:
            has_compatible_layer = False

            for sym_layer in symbol_layers:
                if geometry_checker.is_compatible_symbol_layer(sym_layer):
                    has_compatible_layer = True
                    break

            if has_compatible_layer:
                return True, ""
            else:
                return False, geometry_checker.get_error_message()

        # No symbol layers found
        return False, " - no symbol layers found"


class RasterLayerChecker(LayerCompatibilityChecker):
    """Compatibility checker for raster layers"""

    @staticmethod
    def check(layer: QgsRasterLayer) -> Tuple[bool, str]:
        """Check raster layer compatibility based on provider and type"""
        provider_type = layer.dataProvider().name()

        if provider_type != "wms":
            return False, " - raster provider not supported"

        source = layer.dataProvider().dataSourceUri()
        if "type=xyz" in source.lower():
            return True, ""

        return False, " - only XYZ type WMS supported"


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
                is_compatible, reason = VectorLayerChecker.check(map_layer)
            elif isinstance(map_layer, QgsRasterLayer):
                is_compatible, reason = RasterLayerChecker.check(map_layer)
            else:
                is_compatible, reason = False, " - unsupported layer type"

            if is_compatible:
                compatible_layers.append(layer_info)
            else:
                incompatible_layers.append(layer_info + reason)

        return compatible_layers, incompatible_layers
