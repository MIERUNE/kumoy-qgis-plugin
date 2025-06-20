from abc import ABC, abstractmethod

from qgis.core import QgsSymbolLayer


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
