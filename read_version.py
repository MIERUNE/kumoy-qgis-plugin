import os

from qgis.core import Qgis, QgsMessageLog

from .kumoy.constants import LOG_CATEGORY


def read_version():
    # read version from metadata.txt
    version = "v0.0.0"
    try:
        metadata_path = os.path.join(os.path.dirname(__file__), "./metadata.txt")
        with open(metadata_path, "r") as f:
            for line in f:
                if line.startswith("version="):
                    version = line.split("=")[1].strip()
                    break
    except Exception as e:
        QgsMessageLog.logMessage(
            f"Error reading version from metadata.txt: {e}",
            LOG_CATEGORY,
            Qgis.Warning,
        )
    return version
