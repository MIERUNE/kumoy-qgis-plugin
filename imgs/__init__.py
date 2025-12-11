import os

from qgis.PyQt.QtGui import QIcon

_IMGS_PATH = os.path.dirname(os.path.realpath(__file__))

# generic icon
MAIN_ICON = QIcon(os.path.join(_IMGS_PATH, "icon.svg"))
DARK_MODE_ICON = QIcon(os.path.join(_IMGS_PATH, "icon_dark.svg"))
MAP_ICON = QIcon(os.path.join(_IMGS_PATH, "map.svg"))
RELOAD_ICON = QIcon(os.path.join(_IMGS_PATH, "reload.svg"))
VECTOR_ICON = QIcon(os.path.join(_IMGS_PATH, "vector.svg"))
PIN_ICON = QIcon(os.path.join(_IMGS_PATH, "pin.svg"))
WARNING_ICON = QIcon(os.path.join(_IMGS_PATH, "mIconWarning.svg"))

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
