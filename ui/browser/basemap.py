from qgis.core import (
    QgsApplication,
    QgsDataCollectionItem,
    QgsDataItem,
    QgsMimeDataUtils,
    QgsProject,
    QgsRasterLayer,
)
from qgis.PyQt.QtWidgets import QAction

from ... import i18n
from ..icons import BROWSER_FOLDER_ICON

# (layer name, style id on maptiles.kumoy.io)
BASEMAPS = [
    ("MIERUNE Streets", "streets"),
    ("MIERUNE Gray", "gray"),
    ("MIERUNE Dark", "dark"),
]


def basemap_uri(style: str) -> str:
    # Same datasource as the sample map created by the backend, so the web viewer
    # renders it identically (tilePixelRatio=2 -> 512px tiles). The tile server
    # only checks the referer, which is fixed regardless of the custom server URL.
    return (
        "crs=EPSG:3857&format&type=xyz"
        f"&url=https://maptiles.kumoy.io/latest/{style}/raster/512/{{z}}/{{x}}/{{y}}"
        "&zmax=19&zmin=0&tilePixelRatio=2"
        "&http-header:referer=https://app.kumoy.io/"
    )


def add_basemap_to_map(name: str, style: str) -> QgsRasterLayer:
    layer = QgsRasterLayer(basemap_uri(style), name, "wms")
    project = QgsProject.instance()
    project.addMapLayer(layer, False)
    # Append to the bottom so the basemap doesn't cover existing layers
    project.layerTreeRoot().addLayer(layer)
    return layer


class BasemapItem(QgsDataItem):
    def __init__(self, parent, name: str, style: str):
        QgsDataItem.__init__(
            self,
            QgsDataItem.Custom,
            parent=parent,
            name=name,
            path=f"{parent.path()}/{style}",
        )
        self.style = style
        self.setIcon(QgsApplication.getThemeIcon("/mIconXyz.svg"))
        self.setState(QgsDataItem.Populated)

    def hasDragEnabled(self) -> bool:
        return True

    def mimeUris(self) -> list[QgsMimeDataUtils.Uri]:
        u = QgsMimeDataUtils.Uri()
        u.layerType = "raster"
        u.providerKey = "wms"
        u.name = self.name()
        u.uri = basemap_uri(self.style)
        return [u]

    def actions(self, parent):
        add_action = QAction(i18n.tr("Add to Map"), parent)
        add_action.triggered.connect(self.handleDoubleClick)
        return [add_action]

    def handleDoubleClick(self) -> bool:
        add_basemap_to_map(self.name(), self.style)
        return True


class BasemapRoot(QgsDataCollectionItem):
    """Kumoy-hosted basemaps. Usable without login or project selection."""

    def __init__(self, parent, path: str):
        QgsDataCollectionItem.__init__(self, parent, "MIERUNE MapTiles", path)
        self.setIcon(BROWSER_FOLDER_ICON)

    def createChildren(self):
        return [BasemapItem(self, name, style) for name, style in BASEMAPS]
