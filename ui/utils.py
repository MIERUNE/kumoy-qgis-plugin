from typing import List, Optional

from qgis.core import (
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsLayerTreeNode,
    QgsMapLayer,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)
from qgis.PyQt.QtWidgets import QMessageBox, QWidget

from ..kumoy import constants
from ..pyqt_version import Q_MESSAGEBOX_STD_BUTTON, QT_TEXT_FORMAT_PLAIN, exec_dialog


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


def uri_param(source: str, key: str) -> str:
    """Read `key` from a Kumoy layer source ("project_id=..;vector_id=..;...").

    Parsed here instead of asking the provider object: the URI format is the
    contract between areas, provider attributes are not.
    """
    for part in source.split(";"):
        name, sep, value = part.partition("=")
        if sep and name.strip() == key:
            return value
    return ""


def layers_of(provider_key: str, id_key: str, resource_id: str) -> List[QgsMapLayer]:
    """Layers of the current QGIS project that show the given Kumoy resource."""
    return [
        layer
        for layer in QgsProject.instance().mapLayers().values()
        if layer.providerType() == provider_key
        and uri_param(layer.source(), id_key) == resource_id
    ]


def kumoy_map_open() -> bool:
    """Whether the current QGIS project is a Kumoy map.

    Maps opened from Kumoy carry the `kumoy_map_id` project variable; maps
    read through the Kumoy project storage have a `kumoy:` file name.
    INTEGRATION(C): replace with the project storage's own check if it has one.
    """
    project = QgsProject.instance()
    return bool(
        project.customVariables().get("kumoy_map_id")
        or project.fileName().startswith("kumoy:")
    )


def confirm(parent: Optional[QWidget], title: str, text: str) -> bool:
    """Yes/No question with No as default. Plain text: names come from users."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(title)
    box.setTextFormat(QT_TEXT_FORMAT_PLAIN)
    box.setText(text)
    box.setStandardButtons(Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No)
    box.setDefaultButton(Q_MESSAGEBOX_STD_BUTTON.No)
    exec_dialog(box)
    # exec() returns a plain int under PyQt6, which never equals the enum
    return box.standardButton(box.clickedButton()) == Q_MESSAGEBOX_STD_BUTTON.Yes
