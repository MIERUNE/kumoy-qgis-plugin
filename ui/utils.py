from qgis.PyQt.QtWidgets import QMessageBox, QWidget

from qgis.core import (
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsLayerTreeNode,
    QgsMapLayer,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)

from ..kumoy import constants
from ..pyqt_version import QT_TEXT_FORMAT_PLAIN, exec_dialog


def get_local_layers() -> list[QgsMapLayer]:
    """Return convertible non-Kumoy layers in layer panel order.

    Vectors: any non-Kumoy provider. Rasters: file-backed (``gdal`` provider)
    only — COG conversion reads ``layer.source()`` via gdal, so remote/basemap
    rasters (XYZ, WMS, WCS, ...) have no local file to convert and are
    excluded so the selection dialog does not offer un-uploadable candidates.
    """
    root = QgsProject.instance().layerTreeRoot()
    layers: list[QgsMapLayer] = []

    def _is_convertible(layer: QgsMapLayer) -> bool:
        if isinstance(layer, QgsVectorLayer):
            return (
                layer.dataProvider() is not None
                and layer.dataProvider().name() != constants.DATA_PROVIDER_KEY
            )
        if isinstance(layer, QgsRasterLayer):
            return layer.providerType() == "gdal"
        return False

    def _walk(node: QgsLayerTreeNode) -> None:
        if isinstance(node, QgsLayerTreeLayer):
            layer = node.layer()
            if layer and layer.isValid() and _is_convertible(layer):
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
