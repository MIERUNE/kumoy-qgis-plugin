import os

from qgis.core import Qgis, QgsDataItem, QgsMessageLog
from qgis.PyQt.QtGui import QIcon

from ..imgs import IMGS_PATH
from ..strato.constants import LOG_CATEGORY


class ErrorItem(QgsDataItem):
    """Error item for browser to display error messages"""

    def __init__(self, parent, message=""):
        QgsDataItem.__init__(
            self, QgsDataItem.Custom, parent=parent, name=message, path=""
        )

        self.setIcon(QIcon(os.path.join(IMGS_PATH, "mIconWarning.svg")))
        QgsMessageLog.logMessage(
            f"Error item created: {message}", LOG_CATEGORY, Qgis.Warning
        )
