from typing import TYPE_CHECKING

from .raster import RasterLayerChecker
from .vector import VectorLayerChecker

if TYPE_CHECKING:
    from typing import Type


class CompatibilityChecker:
    """Namespace for layer compatibility checkers"""

    vector: "Type[VectorLayerChecker]" = VectorLayerChecker
    raster: "Type[RasterLayerChecker]" = RasterLayerChecker


__all__ = ["CompatibilityChecker", "VectorLayerChecker", "RasterLayerChecker"]
