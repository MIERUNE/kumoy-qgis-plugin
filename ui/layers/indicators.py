from qgis.core import QgsProject
from qgis.gui import QgsLayerTreeViewIndicator
from qgis.utils import iface

from ...kumoy.constants import DATA_PROVIDER_KEY, RASTER_DATA_PROVIDER_KEY
from ..icons import MAIN_ICON

_KUMOY_TOOLTIP = "Kumoy layer"


def update_kumoy_indicator():
    """Ensure the Kumoy indicator is present on Kumoy layers and removed from other nodes."""
    root = QgsProject.instance().layerTreeRoot()
    view = iface.layerTreeView()

    for node in root.findLayers():
        layer = node.layer()
        is_kumoy = layer is not None and layer.providerType() in (
            DATA_PROVIDER_KEY,
            RASTER_DATA_PROVIDER_KEY,
        )
        existing = _kumoy_indicators(node)
        if is_kumoy:
            if existing:
                continue
            indicator = QgsLayerTreeViewIndicator(view)
            indicator.setToolTip(_KUMOY_TOOLTIP)
            indicator.setIcon(MAIN_ICON)
            view.addIndicator(node, indicator)
        else:
            # QgsLayerTreeView keys indicators by node pointer and never drops
            # entries for destroyed nodes, so a reused address would otherwise
            # inherit a Kumoy icon. Remove them explicitly.
            for indicator in existing:
                view.removeIndicator(node, indicator)
                indicator.deleteLater()


def _kumoy_indicators(node):
    """Return Kumoy indicators set on the given node."""
    view = iface.layerTreeView()
    return [i for i in view.indicators(node) if i.toolTip() == _KUMOY_TOOLTIP]
