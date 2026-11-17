from qgis.PyQt.QtWidgets import QApplication

from ..qgis_version import PROCESSING_ALGORITHM_DIALOG
from . import base


def close_all_processing_dialogs() -> None:
    """Close open upload dialogs and forget the upload destinations.

    Called on logout and unload: both belong to the old login.
    """
    base.forget_project_choices()
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, PROCESSING_ALGORITHM_DIALOG) and isinstance(
            widget.algorithm(), base.KumoyUploadAlgorithm
        ):
            widget.close()
