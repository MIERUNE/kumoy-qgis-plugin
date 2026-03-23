from qgis.PyQt.QtWidgets import QMessageBox, QWidget

from qgis.core import (
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsLayerTreeNode,
    QgsProject,
    QgsVectorLayer,
)

from ..kumoy import constants
from ..pyqt_version import QT_TEXT_FORMAT_PLAIN, exec_dialog


def get_local_vector_layers() -> list[QgsVectorLayer]:
    """Return non-Kumoy vector layers in layer panel order."""
    root = QgsProject.instance().layerTreeRoot()
    layers: list[QgsVectorLayer] = []

    def _walk(node: QgsLayerTreeNode) -> None:
        if isinstance(node, QgsLayerTreeLayer):
            layer = node.layer()
            if (
                layer
                and layer.isValid()
                and isinstance(layer, QgsVectorLayer)
                and layer.dataProvider()
                and layer.dataProvider().name() != constants.DATA_PROVIDER_KEY
            ):
                layers.append(layer)
        elif isinstance(node, QgsLayerTreeGroup):
            for child in node.children():
                _walk(child)

    _walk(root)
    return layers


def show_plain_text_message(parent: QWidget, title: str, message: str) -> None:
    """Show a plain-text message box to avoid rendering HTML in user data."""
    msg_box = QMessageBox(parent)
    msg_box.setWindowTitle(title)
    msg_box.setText(message)
    msg_box.setTextFormat(QT_TEXT_FORMAT_PLAIN)
    exec_dialog(msg_box)
