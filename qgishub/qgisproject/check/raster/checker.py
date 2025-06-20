from typing import Tuple

from qgis.core import QgsRasterLayer

from ..base import BaseCompatibilityChecker


class RasterLayerChecker(BaseCompatibilityChecker):
    """Compatibility checker for raster layers"""

    def check(self, layer: QgsRasterLayer) -> Tuple[bool, str]:
        """Check if a raster layer is compatible with MapLibre"""
        provider_type = layer.dataProvider().name()

        if provider_type != "wms":
            return False, " - raster provider not supported"

        source = layer.dataProvider().dataSourceUri()
        if "type=xyz" in source.lower():
            return True, ""

        return False, " - only XYZ type WMS supported"
