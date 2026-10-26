"""register_xyz_connections のユニットテスト"""

import pytest
from qgis.core import QgsRasterLayer, QgsXyzConnectionUtils

pytestmark = pytest.mark.usefixtures("qgis_plugin_path")


def test_register_xyz_connections_creates_valid_layers():
    from plugin_dir.kumoy.basemap import BASEMAPS, register_xyz_connections

    register_xyz_connections()
    register_xyz_connections()  # idempotent

    try:
        for name, style in BASEMAPS:
            conn = QgsXyzConnectionUtils.connection(name)
            assert f"/latest/{style}/raster/512/" in conn.url
            assert conn.tilePixelRatio == 2
            assert conn.httpHeaders.headers()["referer"] == "https://app.kumoy.io/"
            assert QgsRasterLayer(conn.encodedUri(), name, "wms").isValid()
    finally:
        for name, _ in BASEMAPS:
            QgsXyzConnectionUtils.deleteConnection(name)
