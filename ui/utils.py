from qgis.core import (
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsLayerTreeNode,
    QgsProject,
    QgsVectorLayer,
)

from ..kumoy import constants


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
