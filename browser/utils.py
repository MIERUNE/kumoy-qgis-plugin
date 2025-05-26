import os

from PyQt5.QtGui import QIcon
from qgis.core import QgsDataItem, QgsMessageLog, Qgis

from ..imgs import IMGS_PATH


class ErrorItem(QgsDataItem):
    """Error item for browser to display error messages"""

    def __init__(self, parent, message=""):
        QgsDataItem.__init__(
            self, QgsDataItem.Custom, parent=parent, name=message, path=""
        )

        self.setIcon(QIcon(os.path.join(IMGS_PATH, "mIconWarning.svg")))
        QgsMessageLog.logMessage(
            f"Error item created: {message}", "QGISHub", Qgis.Warning
        )
