from abc import ABC, abstractmethod
from typing import Tuple

from qgis.core import (
    QgsMapLayer,
    QgsRasterLayer,
    QgsSymbol,
    QgsVectorLayer,
    QgsWkbTypes,
)

from .geom_symbol import (
    GeometrySymbolChecker,
    LineSymbolChecker,
    PointSymbolChecker,
    PolygonSymbolChecker,
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


class VectorLayerChecker(LayerCompatibilityChecker):
    """Compatibility checker for vector layers"""

    @staticmethod
    def check(layer: QgsVectorLayer) -> Tuple[bool, str]:
        """Internal method to check layer compatibility"""
        geometry_checkers = {
            QgsWkbTypes.PointGeometry: PointSymbolChecker(),
            QgsWkbTypes.LineGeometry: LineSymbolChecker(),
            QgsWkbTypes.PolygonGeometry: PolygonSymbolChecker(),
        }

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
        if geometry_type not in geometry_checkers:
            return False, " - unsupported geometry type"

        geometry_checker: GeometrySymbolChecker = geometry_checkers[geometry_type]
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
