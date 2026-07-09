from qgis.PyQt.QtWidgets import QApplication

from ..qgis_version import PROCESSING_ALGORITHM_DIALOG
from .upload_vector.algorithm import UploadVectorAlgorithm


def close_all_processing_dialogs():
    """Close all open dialogs related to the plugin"""
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, PROCESSING_ALGORITHM_DIALOG):
            alg = widget.algorithm()
            if isinstance(alg, UploadVectorAlgorithm):
                widget.close()
