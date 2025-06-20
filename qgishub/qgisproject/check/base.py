from abc import ABC, abstractmethod
from typing import Tuple

from qgis.core import QgsMapLayer


class BaseCompatibilityChecker(ABC):
    """Abstract base class for all compatibility checkers"""

    @abstractmethod
    def check(self, layer: QgsMapLayer) -> Tuple[bool, str]:
        """
        Check if a layer is compatible.

        Returns:
            Tuple of (is_compatible, reason_if_not_compatible)
        """
        pass
