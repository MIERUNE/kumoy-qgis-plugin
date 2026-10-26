from typing import Optional

from qgis.core import Qgis, QgsMessageLog, QgsSettingsTreeNode, QgsSettingsTree

from .constants import LOG_CATEGORY

# (connection name, style id on maptiles.kumoy.io)
BASEMAPS = [
    ("MIERUNE MapTiles Streets", "streets"),
    ("MIERUNE MapTiles Gray", "gray"),
    ("MIERUNE MapTiles Dark", "dark"),
]


def _xyz_connections_node() -> Optional[QgsSettingsTreeNode]:
    # QgsXyzConnection(Utils) is not exposed to Python, so use the settings tree
    # that QGIS itself reads XYZ connections from.
    node = QgsSettingsTree.node("connections")
    node = node.childNode("xyz") if node else None
    if node is None:
        QgsMessageLog.logMessage(
            "XYZ connection settings not found; skipped basemap connections",
            LOG_CATEGORY,
            Qgis.Warning,
        )
    return node


def add_xyz_connections() -> None:
    """Add Kumoy basemaps to QGIS's XYZ Tiles connections unless already present.

    Same datasource as the sample map created by the backend, so the web viewer
    renders it identically (tilePixelRatio=2 -> 512px tiles). The tile server
    only checks the referer, which is fixed regardless of the custom server URL.
    """
    node = _xyz_connections_node()
    if node is None:
        return

    existing = node.items()
    for name, style in BASEMAPS:
        if name in existing:
            continue
        values = {
            "url": f"https://maptiles.kumoy.io/latest/{style}/raster/512/{{z}}/{{x}}/{{y}}",
            "zmin": 0,
            "zmax": 19,
            "tile-pixel-ratio": 2,
            "http-header": {"referer": "https://app.kumoy.io/"},
        }
        for key, value in values.items():
            node.childSetting(key).setVariantValue(value, [name])


def remove_xyz_connections() -> None:
    """Remove the Kumoy basemaps from QGIS's XYZ Tiles connections if present."""
    node = _xyz_connections_node()
    if node is None:
        return

    existing = node.items()
    for name, _ in BASEMAPS:
        if name in existing:
            node.deleteItem(name)
