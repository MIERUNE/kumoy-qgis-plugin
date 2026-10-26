from qgis.core import QgsHttpHeaders, QgsXyzConnection, QgsXyzConnectionUtils

# (connection name, style id on maptiles.kumoy.io)
BASEMAPS = [
    ("MIERUNE Streets", "streets"),
    ("MIERUNE Gray", "gray"),
    ("MIERUNE Dark", "dark"),
]


def register_xyz_connections() -> None:
    """Add Kumoy basemaps to QGIS's XYZ Tiles connections (overwrites same names).

    Same datasource as the sample map created by the backend, so the web viewer
    renders it identically (tilePixelRatio=2 -> 512px tiles). The tile server
    only checks the referer, which is fixed regardless of the custom server URL.
    """
    for name, style in BASEMAPS:
        conn = QgsXyzConnection()
        conn.name = name
        conn.url = (
            f"https://maptiles.kumoy.io/latest/{style}/raster/512/{{z}}/{{x}}/{{y}}"
        )
        conn.zMin = 0
        conn.zMax = 19
        conn.tilePixelRatio = 2
        conn.httpHeaders = QgsHttpHeaders({"referer": "https://app.kumoy.io/"})
        QgsXyzConnectionUtils.addConnection(conn)
