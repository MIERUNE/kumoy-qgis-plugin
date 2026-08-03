from qgis.core import QgsProject
from qgis.gui import QgsLayerTreeViewIndicator
from qgis.utils import iface

from ... import i18n
from ...kumoy.constants import DATA_PROVIDER_KEY, RASTER_DATA_PROVIDER_KEY
from ..icons import MAIN_ICON

# Marker property, not the tooltip: the tooltip is translated and must not be
# relied on to identify our own indicators.
_KUMOY_INDICATOR_PROPERTY = "kumoyIndicator"


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
            indicator.setProperty(_KUMOY_INDICATOR_PROPERTY, True)
            indicator.setToolTip(i18n.tr("Kumoy layer"))
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
    return [i for i in view.indicators(node) if i.property(_KUMOY_INDICATOR_PROPERTY)]
