from typing import Tuple

from qgis.core import QgsSymbol, QgsVectorLayer, QgsWkbTypes

from ..base import BaseCompatibilityChecker
from .symbol import (
    GeometrySymbolChecker,
    LineSymbolChecker,
    PointSymbolChecker,
    PolygonSymbolChecker,
)


class VectorLayerChecker(BaseCompatibilityChecker):
    """Compatibility checker for vector layers"""

    @staticmethod
    def check(layer: QgsVectorLayer) -> Tuple[bool, str]:
        """Check if a vector layer is compatible with MapLibre"""
        geometry_checkers = {
            QgsWkbTypes.PointGeometry: PointSymbolChecker(),
            QgsWkbTypes.LineGeometry: LineSymbolChecker(),
            QgsWkbTypes.PolygonGeometry: PolygonSymbolChecker(),
        }

        provider_type = layer.dataProvider().name()

        if provider_type != "strato":
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
