import os
from typing import Dict

from qgis.PyQt.QtCore import QRectF
from qgis.PyQt.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from qgis.PyQt.QtWidgets import QApplication

from ...pyqt_version import Q_PAINTER_RENDER_HINT, QT_PEN_CAP_STYLE
from .darkmode import is_in_darkmode

_IMGS_PATH = os.path.dirname(os.path.realpath(__file__))

# generic icon
MAIN_ICON = (
    QIcon(os.path.join(_IMGS_PATH, "icon.svg"))
    if not is_in_darkmode()
    else QIcon(os.path.join(_IMGS_PATH, "icon_dark.svg"))
)
MAP_ICON = QIcon(os.path.join(_IMGS_PATH, "map.svg"))
RELOAD_ICON = QIcon(os.path.join(_IMGS_PATH, "reload.svg"))
VECTOR_ICON = QIcon(os.path.join(_IMGS_PATH, "vector.svg"))
RASTER_ICON = QIcon(os.path.join(_IMGS_PATH, "raster.svg"))
PIN_ICON = QIcon(os.path.join(_IMGS_PATH, "pin.svg"))
SEARCH_ICON = QIcon(os.path.join(_IMGS_PATH, "search.svg"))
WARNING_ICON = QIcon(os.path.join(_IMGS_PATH, "mIconWarning.svg"))
GRID_ICON = QIcon(os.path.join(_IMGS_PATH, "grid.svg"))
LIST_ICON = QIcon(os.path.join(_IMGS_PATH, "list.svg"))
# White: drawn on a team color / gray badge
TEAM_ICON = QIcon(os.path.join(_IMGS_PATH, "team.svg"))
ORGANIZATION_ICON = QIcon(os.path.join(_IMGS_PATH, "organization.svg"))

# browser
BROWSER_FOLDER_ICON = QIcon(os.path.join(_IMGS_PATH, "browser_folder.svg"))
BROWSER_GEOMETRY_LINESTRING_ICON = QIcon(
    os.path.join(_IMGS_PATH, "browser_geometry_linestring.svg")
)
BROWSER_GEOMETRY_POINT_ICON = QIcon(
    os.path.join(_IMGS_PATH, "browser_geometry_point.svg")
)
BROWSER_GEOMETRY_POLYGON_ICON = QIcon(
    os.path.join(_IMGS_PATH, "browser_geometry_polygon.svg")
)
BROWSER_MAP_ICON = QIcon(os.path.join(_IMGS_PATH, "browser_map.svg"))
BROWSER_RASTER_ICON = QIcon(os.path.join(_IMGS_PATH, "browser_raster.svg"))


def badge_pixmap(color: str, icon: QIcon, size: int) -> QPixmap:
    """`icon` (white) on a rounded square of `color` (#rrggbb), like the web app."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(Q_PAINTER_RENDER_HINT.Antialiasing)
    painter.setPen(QColor(0, 0, 0, 0))
    painter.setBrush(QColor(color))
    radius = size / 4
    painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)
    inset = size // 8
    icon.paint(painter, inset, inset, size - 2 * inset, size - 2 * inset)
    painter.end()
    return pixmap


# Steps of the progress gauge: icons are cached per step, and the Layers
# panel repaints only when the step changes
_GAUGE_STEPS = 20
_gauge_icons: Dict[int, QIcon] = {}


def progress_icon(percent: float) -> QIcon:
    """A ring that fills clockwise from 12 o'clock as `percent` (0-100) grows."""
    step = round(max(0.0, min(100.0, percent)) / 100 * _GAUGE_STEPS)
    icon = _gauge_icons.get(step)
    if icon is None:
        icon = QIcon()
        # Drawn per size instead of scaled: a scaled 16 px ring blurs
        for size in (16, 24, 32, 48):
            icon.addPixmap(_gauge_pixmap(size, step / _GAUGE_STEPS))
        _gauge_icons[step] = icon
    return icon


def _gauge_pixmap(size: int, fraction: float) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    # The palette's highlight follows the theme (light/dark, OS accent)
    accent = QApplication.palette().highlight().color()
    track = QColor(accent)
    track.setAlpha(60)
    width = max(2.0, size / 7)
    inset = width / 2 + size / 16
    rect = QRectF(inset, inset, size - 2 * inset, size - 2 * inset)

    painter = QPainter(pixmap)
    painter.setRenderHint(Q_PAINTER_RENDER_HINT.Antialiasing)
    pen = QPen(track, width)
    pen.setCapStyle(QT_PEN_CAP_STYLE.FlatCap)
    painter.setPen(pen)
    painter.drawEllipse(rect)
    if fraction > 0:
        pen.setColor(accent)
        pen.setCapStyle(QT_PEN_CAP_STYLE.RoundCap)
        painter.setPen(pen)
        # Angles are in 1/16 degree; 90 degrees is 12 o'clock and a negative
        # span runs clockwise
        painter.drawArc(rect, 90 * 16, -round(fraction * 360 * 16))
    painter.end()
    return pixmap
