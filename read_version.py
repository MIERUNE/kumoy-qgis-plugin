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
    """Parse version string to tuple of ints, ignoring pre-release suffixes.

    Examples:
        'v1.0.0'       -> (1, 0, 0)
        'v1.0.0-beta'  -> (1, 0, 0)
        'v1.0-beta'    -> (1, 0)
        'v1.0.alpha'   -> (1, 0)
        '1.2.3'        -> (1, 2, 3)
    """
    parts = []
    for segment in v.lstrip("v").split("-")[0].split("."):
        if segment.isdigit():
            parts.append(int(segment))
        else:
            break  # stop at first non-numeric part (e.g. "alpha", "beta")
    return tuple(parts)


def is_plugin_version_compatible(min_version: str) -> bool:
    """
    Check if current plugin version meets the minimum required version.
    Returns True if compatible.

    Args:
        min_version: Minimum required version string (e.g. 'v1.0.0')

    Returns:
        bool: True if compatible, False if too old
    """
    plugin_version = read_version()

    if not min_version or plugin_version == "dev":
        return True

    return _parse_version(plugin_version) >= _parse_version(min_version)
