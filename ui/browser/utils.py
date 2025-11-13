import os

from qgis.core import Qgis, QgsDataItem, QgsMessageLog
from qgis.PyQt.QtCore import QCoreApplication
from qgis.utils import iface

from ...imgs import WARNING_ICON
from ...strato.constants import LOG_CATEGORY


class ErrorItem(QgsDataItem):
    """Error item for browser to display error messages"""

    def __init__(self, parent, message=""):
        QgsDataItem.__init__(
            self, QgsDataItem.Custom, parent=parent, name=message, path=""
        )

        self.setIcon(WARNING_ICON)
        QgsMessageLog.logMessage(
            f"Error item created: {message}", LOG_CATEGORY, Qgis.Warning
        )


def notify_browser_error(message: str) -> None:
    iface.messageBar().pushCritical(
        QCoreApplication.translate("StratoBrowser", "STRATO Maintenance"),
        message,
    )
