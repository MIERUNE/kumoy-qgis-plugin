"""register_xyz_connections のユニットテスト"""

import pytest
from qgis.core import QgsApplication, QgsRasterLayer, QgsSettingsTree

pytestmark = pytest.mark.usefixtures("qgis_plugin_path")


def test_registered_connections_appear_in_xyz_browser():
    from plugin_dir.kumoy.basemap import BASEMAPS, register_xyz_connections

    register_xyz_connections()
    register_xyz_connections()  # idempotent

    try:
        # Read back through QGIS's own XYZ Tiles browser to verify the settings keys
        provider = next(
            p
            for p in QgsApplication.dataItemProviderRegistry().providers()
            if p.name() == "XYZ Tiles"
        )
        items = {
            item.name(): item
            for item in provider.createDataItem("", None).createChildren()
        }
        for name, style in BASEMAPS:
            uri = items[name].mimeUris()[0].uri
            assert f"/latest/{style}/raster/512/" in uri
            assert "tilePixelRatio=2" in uri
            assert "http-header:referer=https://app.kumoy.io/" in uri
            assert QgsRasterLayer(uri, name, "wms").isValid()
    finally:
        node = QgsSettingsTree.node("connections").childNode("xyz")
        for name, _ in BASEMAPS:
            node.deleteItem(name)
