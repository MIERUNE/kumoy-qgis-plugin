from qgis.PyQt.QtCore import QTimer
from qgis.core import QgsProject
from qgis.gui import QgsLayerTreeViewIndicator
from qgis.utils import iface

from .icons import MAIN_ICON
from ..kumoy.constants import DATA_PROVIDER_KEY


def update_kumoy_indicator():
    """Set Kumoy icon as indicator on Kumoy provided layer"""
    root = QgsProject.instance().layerTreeRoot()
    view = iface.layerTreeView()

    missing_nodes = False
    for layer in QgsProject.instance().mapLayers().values():
        if layer.providerType() != DATA_PROVIDER_KEY:
            continue
        node = root.findLayer(layer.id())
        if not node:
            # node made missing when project is loading, retry later
            missing_nodes = True
            continue
        if _has_kumoy_indicator(node):
            continue
        indicator = QgsLayerTreeViewIndicator(view)
        indicator.setToolTip("Kumoy layer")
        indicator.setIcon(MAIN_ICON)
        view.addIndicator(node, indicator)

    # HACK: retry in 100ms if nodes were not yet created when loading map
    if missing_nodes:
        QTimer.singleShot(100, update_kumoy_indicator)


def _has_kumoy_indicator(node):
    """Check if the given node has Kumoy indicator set."""
    view = iface.layerTreeView()
    indicators = view.indicators(node)
    for indicator in indicators:
        if indicator.toolTip() == "Kumoy layer":
            return True
    return False
