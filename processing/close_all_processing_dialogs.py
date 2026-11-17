from qgis.PyQt.QtWidgets import QApplication

from ..qgis_version import PROCESSING_ALGORITHM_DIALOG
from .base import KumoyUploadAlgorithm


def close_all_processing_dialogs() -> None:
    """Close open upload dialogs: their project lists belong to the old login."""
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, PROCESSING_ALGORITHM_DIALOG) and isinstance(
            widget.algorithm(), KumoyUploadAlgorithm
        ):
            widget.close()
