"""add_xyz_connections / remove_xyz_connections のユニットテスト"""

from urllib.parse import unquote

import pytest
from qgis.core import QgsApplication, QgsRasterLayer, QgsSettingsTree

pytestmark = pytest.mark.usefixtures("qgis_plugin_path")


def _xyz_browser_items() -> dict:
    # Read back through QGIS's own XYZ Tiles browser to verify the settings keys
    provider = next(
        p
        for p in QgsApplication.dataItemProviderRegistry().providers()
        if p.name() == "XYZ Tiles"
    )
    return {
        item.name(): item for item in provider.createDataItem("", None).createChildren()
    }


def test_add_and_remove_xyz_connections():
    from plugin_dir.kumoy.basemap import (
        BASEMAPS,
        add_xyz_connections,
        remove_xyz_connections,
    )

    node = QgsSettingsTree.node("connections").childNode("xyz")
    edited_name = BASEMAPS[0][0]

    try:
        add_xyz_connections()

        items = _xyz_browser_items()
        for name, style in BASEMAPS:
            uri = items[name].mimeUris()[0].uri
            # QGIS 4 percent-encodes the parameter values, QGIS 3 doesn't
            decoded = unquote(uri)
            assert f"/latest/{style}/raster/512/" in decoded
            assert "tilePixelRatio=2" in decoded
            assert "http-header:referer=https://app.kumoy.io/" in decoded
            assert QgsRasterLayer(uri, name, "wms").isValid()

        # An existing connection is left as is
        node.childSetting("zmax").setVariantValue(10, [edited_name])
        add_xyz_connections()
        assert node.childSetting("zmax").valueAsVariant([edited_name]) in (10, "10")

        remove_xyz_connections()
        remove_xyz_connections()  # no-op when already removed
        assert not set(node.items()) & {name for name, _ in BASEMAPS}
    finally:
        for name, _ in BASEMAPS:
            node.deleteItem(name)
