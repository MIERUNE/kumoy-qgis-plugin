"""The Layers panel indicator of a Kumoy layer whose data is still downloading.

Shared by vectors (first download) and rasters (COG download): a gauge that
fills with the progress, a warning that retries when clicked after a failure,
and nothing otherwise.
"""

from typing import Callable, Dict, Iterable, Optional

from qgis.core import QgsMapLayer, QgsProject
from qgis.gui import QgsLayerTreeViewIndicator
from qgis.utils import iface

from ..icons import WARNING_ICON, progress_icon

# Marks our indicators; the tooltip is translated and cannot identify them
PROPERTY = "kumoyDownloadIndicator"

# Layer ID -> what clicking its failed indicator does. Kept here, not on the
# indicator: its Python wrapper does not survive being fetched from the view
_retry: Dict[str, Callable[[], None]] = {}


def show_progress(layers: Iterable[QgsMapLayer], percent: float, text: str) -> None:
    for layer in layers:
        _retry.pop(layer.id(), None)
        _set(layer, progress_icon(percent), text)


def show_error(
    layers: Iterable[QgsMapLayer], text: str, retry: Callable[[], None]
) -> None:
    for layer in layers:
        _retry[layer.id()] = retry
        _set(layer, WARNING_ICON, text)


def hide(layers: Iterable[QgsMapLayer]) -> None:
    view = _view()
    for layer in layers:
        _retry.pop(layer.id(), None)
        node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
        if view is None or node is None:
            continue
        for indicator in _ours(view, node):
            view.removeIndicator(node, indicator)
            indicator.deleteLater()


def _view():
    return iface.layerTreeView() if iface is not None else None


def _ours(view, node):
    return [i for i in view.indicators(node) if i.property(PROPERTY)]


def _set(layer: QgsMapLayer, icon, text: str) -> None:
    view = _view()
    node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
    if view is None or node is None:
        return
    existing = _ours(view, node)
    if existing:
        indicator: Optional[QgsLayerTreeViewIndicator] = existing[0]
    else:
        indicator = QgsLayerTreeViewIndicator(view)
        indicator.setProperty(PROPERTY, True)
        layer_id = layer.id()
        indicator.clicked.connect(lambda _index: _on_clicked(layer_id))
        view.addIndicator(node, indicator)
    indicator.setIcon(icon)
    indicator.setToolTip(text)


def _on_clicked(layer_id: str) -> None:
    retry = _retry.get(layer_id)
    if retry is not None:
        retry()
