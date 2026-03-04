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


def _parse_version(v: str) -> tuple:
    return tuple(int(x) for x in v.lstrip("v").split("."))


def is_plugin_version_compatible(min_version: str) -> bool:
    """
    Check if current plugin version meets the minimum required version.
    Returns True if compatible (or if version is 'dev').

    Args:
        min_version: Minimum required version string (e.g. 'v1.0.0')

    Returns:
        bool: True if compatible, False if too old
    """
    plugin_version = read_version()

    if not min_version or plugin_version == "dev":
        return True

    return _parse_version(plugin_version) >= _parse_version(min_version)
