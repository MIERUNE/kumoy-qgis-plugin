"""Kumoy indicator in the Layers panel.

Kumoy layers must carry the Kumoy icon indicator however they enter the project:
added one by one from the Browser, or opened as part of a saved Kumoy map. The latter
is the tricky one: while a project is read, the layer tree nodes only hold the layer
id and are bound to their layer after the last signal the plugin listens to.

Memory layers stand in for Kumoy layers (the module's provider key is patched to
"memory"). They are valid and survive a project save/read like real Kumoy layers, and
need no registered provider: a stub registered under the real key would clash with the
one in test_map_extent.py (a provider key can only be registered once per session).
"""

import pytest

GEOJSON = (
    '{"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},'
    ' "geometry": {"type": "Point", "coordinates": [0, 0]}}]}'
)


@pytest.fixture
def indicators(qgis_app, monkeypatch):
    from plugin_dir.ui.layers import indicators

    monkeypatch.setattr(indicators, "DATA_PROVIDER_KEY", "memory")
    return indicators


@pytest.fixture
def layer_tree_view(qgis_app, indicators, monkeypatch):
    """Layer tree view stand-in, with the slot wired the way KumoyPlugin.initGui does.

    The project and its layer tree are real, so the signals fire in the real order.
    The view is a stub because the slot only needs indicators / addIndicator /
    removeIndicator, and a real QgsLayerTreeView is a widget whose event processing
    crashes under xvfb in emulated (amd64 on arm64) runs.
    """
    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import QObject

    class _View(QObject):
        def __init__(self):
            super().__init__()
            self._by_layer_id = {}

        def indicators(self, node):
            return list(self._by_layer_id.get(node.layerId(), []))

        def addIndicator(self, node, indicator):
            self._by_layer_id.setdefault(node.layerId(), []).append(indicator)

        def removeIndicator(self, node, indicator):
            self._by_layer_id[node.layerId()].remove(indicator)

    view = _View()

    class _Iface:
        def layerTreeView(self):
            return view

    monkeypatch.setattr(indicators, "iface", _Iface())

    project = QgsProject.instance()
    project.clear()
    root = project.layerTreeRoot()
    slot = indicators.update_kumoy_indicator
    root.removedChildren.connect(slot)
    root.addedChildren.connect(slot)
    project.layersAdded.connect(slot)

    yield view

    project.layersAdded.disconnect(slot)
    root.addedChildren.disconnect(slot)
    root.removedChildren.disconnect(slot)
    project.clear()


def _kumoy_layer(name="points"):
    from qgis.core import QgsVectorLayer

    layer = QgsVectorLayer("Point?crs=EPSG:4326", name, "memory")
    assert layer.isValid()
    return layer


def _other_layer(tmp_path, name="other"):
    """A layer from a provider that is not Kumoy's."""
    from qgis.core import QgsVectorLayer

    path = tmp_path / f"{name}.geojson"
    path.write_text(GEOJSON)
    layer = QgsVectorLayer(str(path), name, "ogr")
    assert layer.isValid()
    return layer


def _n_kumoy_indicators(view, indicators, name):
    """Number of Kumoy indicators on the layer-tree node of the layer called `name`."""
    from qgis.core import QgsProject

    nodes = [
        n
        for n in QgsProject.instance().layerTreeRoot().findLayers()
        if n.name() == name
    ]
    assert len(nodes) == 1, f"expected exactly one node named {name!r}"
    return sum(
        1
        for i in view.indicators(nodes[0])
        if i.property(indicators._KUMOY_INDICATOR_PROPERTY)
    )


def test_kumoy_layer_added_to_project_gets_indicator(layer_tree_view, indicators):
    from qgis.core import QgsProject

    QgsProject.instance().addMapLayer(_kumoy_layer())

    assert _n_kumoy_indicators(layer_tree_view, indicators, "points") == 1


def test_indicator_is_not_duplicated(layer_tree_view, indicators, tmp_path):
    from qgis.core import QgsProject

    QgsProject.instance().addMapLayer(_kumoy_layer())
    # Every addedChildren / removedChildren / layersAdded fires the same slot.
    indicators.update_kumoy_indicator()
    QgsProject.instance().addMapLayer(_other_layer(tmp_path))

    assert _n_kumoy_indicators(layer_tree_view, indicators, "points") == 1


def test_other_layer_gets_no_indicator(layer_tree_view, indicators, tmp_path):
    from qgis.core import QgsProject

    QgsProject.instance().addMapLayer(_other_layer(tmp_path))

    assert _n_kumoy_indicators(layer_tree_view, indicators, "other") == 0


def test_kumoy_layers_get_indicator_when_a_project_is_opened(
    layer_tree_view, indicators, tmp_path
):
    """Opening a saved Kumoy map must show the indicator on its Kumoy layers.

    Regression: the slot used node.layer(), which is still None for every node while
    a project is being read, so no layer was ever marked.
    """
    from qgis.core import QgsProject

    project = QgsProject.instance()
    project.addMapLayer(_other_layer(tmp_path))
    project.addMapLayer(_kumoy_layer("points"))
    project.addMapLayer(_kumoy_layer("lines"))
    path = str(tmp_path / "map.qgs")
    assert project.write(path)

    project.clear()
    assert project.read(path)

    assert _n_kumoy_indicators(layer_tree_view, indicators, "points") == 1
    assert _n_kumoy_indicators(layer_tree_view, indicators, "lines") == 1
    assert _n_kumoy_indicators(layer_tree_view, indicators, "other") == 0


def test_stale_kumoy_indicator_is_removed_from_other_nodes(
    layer_tree_view, indicators, tmp_path
):
    """A Kumoy indicator left on a node that is not a Kumoy layer is dropped.

    QgsLayerTreeView keys indicators by node pointer and never forgets destroyed
    nodes, so a new node allocated at the same address would inherit the icon.
    The reuse itself cannot be forced, so the leftover is attached by hand.
    """
    from qgis.core import QgsProject
    from qgis.gui import QgsLayerTreeViewIndicator

    QgsProject.instance().addMapLayer(_other_layer(tmp_path))
    (node,) = QgsProject.instance().layerTreeRoot().findLayers()

    stale = QgsLayerTreeViewIndicator(layer_tree_view)
    stale.setProperty(indicators._KUMOY_INDICATOR_PROPERTY, True)
    layer_tree_view.addIndicator(node, stale)
    assert _n_kumoy_indicators(layer_tree_view, indicators, "other") == 1

    indicators.update_kumoy_indicator()

    assert _n_kumoy_indicators(layer_tree_view, indicators, "other") == 0
