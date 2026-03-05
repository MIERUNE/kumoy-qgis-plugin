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


def is_plugin_version_compatible(plugin_version: str, min_version: str) -> bool:
    """
    Check if current plugin version meets the minimum required version.
    Returns True if compatible.

    Args:
        plugin_version: Current plugin version string (e.g. 'v1.2.3')
        min_version: Minimum required version string (e.g. 'v1.0.0')

    Returns:
        bool: True if compatible, False if too old
    """
    if not min_version or plugin_version == "dev":
        return True

    current = _parse_version(plugin_version)
    minimum = _parse_version(min_version)
    # Pad the shorter version with zeros for proper comparison (e.g. (1, 0) -> (1, 0, 0))
    length = max(len(current), len(minimum))
    current = current + (0,) * (length - len(current))
    minimum = minimum + (0,) * (length - len(minimum))
    return current >= minimum
