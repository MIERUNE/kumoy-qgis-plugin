from qgis.core import QgsProject
from qgis.gui import QgsLayerTreeViewIndicator
from qgis.utils import iface

from ...kumoy.constants import DATA_PROVIDER_KEY
from ..icons import MAIN_ICON


def update_kumoy_indicator():
    """Set Kumoy icon as indicator on Kumoy provided layer"""
    root = QgsProject.instance().layerTreeRoot()
    view = iface.layerTreeView()

    for layer in QgsProject.instance().mapLayers().values():
        if layer.providerType() != DATA_PROVIDER_KEY:
            continue
        node = root.findLayer(layer.id())
        if not node:
            continue
        if _has_kumoy_indicator(node):
            continue
        indicator = QgsLayerTreeViewIndicator(view)
        indicator.setToolTip("Kumoy layer")
        indicator.setIcon(MAIN_ICON)
        view.addIndicator(node, indicator)


def _has_kumoy_indicator(node):
    """Check if the given node has Kumoy indicator set."""
    view = iface.layerTreeView()
    indicators = view.indicators(node)
    for indicator in indicators:
        if indicator.toolTip() == "Kumoy layer":
            return True
    return False
