from qgis.PyQt.QtWidgets import QApplication, QDialog

from processing.gui.AlgorithmDialog import AlgorithmDialog

from .upload_vector.algorithm import UploadVectorAlgorithm


def closeAllDialogs():
    """Close all open dialogs related to the plugin"""
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, AlgorithmDialog):
            alg = widget.algorithm()
            if isinstance(alg, UploadVectorAlgorithm):
                widget.close()
