import os

from qgis.PyQt.QtGui import QIcon

IMGS_PATH = os.path.dirname(os.path.realpath(__file__))

MAP_ICON = QIcon(os.path.join(IMGS_PATH, "map.svg"))
RELOAD_ICON = QIcon(os.path.join(IMGS_PATH, "reload.svg"))
VECTOR_ICON = QIcon(os.path.join(IMGS_PATH, "vector.svg"))
