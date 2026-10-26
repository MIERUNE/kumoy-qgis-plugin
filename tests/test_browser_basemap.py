"""add_basemap_to_map のユニットテスト"""

import pytest
from qgis.core import QgsProject, QgsVectorLayer

pytestmark = pytest.mark.usefixtures("qgis_plugin_path")


def test_add_basemap_appends_valid_layer_to_bottom():
    from plugin_dir.ui.browser.basemap import add_basemap_to_map

    project = QgsProject.instance()
    project.clear()
    project.addMapLayer(QgsVectorLayer("Point?crs=EPSG:4326", "points", "memory"))

    layer = add_basemap_to_map("MIERUNE Streets", "streets")

    try:
        assert layer.isValid()
        assert project.layerTreeRoot().children()[-1].layer() == layer
    finally:
        project.clear()
