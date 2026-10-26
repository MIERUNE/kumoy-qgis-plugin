from qgis.core import Qgis, QgsMessageLog, QgsSettingsTree

from .constants import LOG_CATEGORY

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
    # QgsXyzConnection(Utils) is not exposed to Python, so write the settings tree
    # that QGIS itself reads XYZ connections from.
    node = QgsSettingsTree.node("connections")
    node = node.childNode("xyz") if node else None
    if node is None:
        QgsMessageLog.logMessage(
            "XYZ connection settings not found; skipped adding basemaps",
            LOG_CATEGORY,
            Qgis.Warning,
        )
        return

    for name, style in BASEMAPS:
        values = {
            "url": f"https://maptiles.kumoy.io/latest/{style}/raster/512/{{z}}/{{x}}/{{y}}",
            "zmin": 0,
            "zmax": 19,
            "tile-pixel-ratio": 2,
            "http-header": {"referer": "https://app.kumoy.io/"},
        }
        for key, value in values.items():
            node.childSetting(key).setVariantValue(value, [name])
