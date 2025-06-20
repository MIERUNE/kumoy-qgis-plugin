from .raster import RasterLayerChecker
from .vector import VectorLayerChecker


class CompatibilityChecker:
    """Namespace for layer compatibility checkers"""

    vector = VectorLayerChecker
    raster = RasterLayerChecker


__all__ = ["CompatibilityChecker", "VectorLayerChecker", "RasterLayerChecker"]
