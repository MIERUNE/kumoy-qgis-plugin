from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsMessageLog, QgsProject
from qgis.PyQt.QtXml import QDomDocument


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


def restore_project_crs_if_invalid(qgisproject_xml: str) -> None:
    """Restore the project CRS if it became invalid after loading.

    This handles the case where a project saved by a newer QGIS version (e.g. QGIS 4)
    contains a WKT that an older QGIS version (e.g. QGIS 3) cannot parse, resulting
    in a null/invalid project CRS.

    Should be called immediately after QgsProject is loaded.

    Args:
        qgisproject_xml: Raw XML string of the .qgs project file
    """
    project = QgsProject.instance()
    if project.crs().isValid():
        return

    crs = _read_project_crs_from_xml(qgisproject_xml)
    if not crs.isValid():
        return

    project.setCrs(crs)
    QgsMessageLog.logMessage(
        f"Project CRS was invalid after loading; restored to {crs.authid()}",
        "Kumoy",
        Qgis.Warning,
    )


def _read_project_crs_from_xml(
    qgisproject_xml: str,
) -> QgsCoordinateReferenceSystem:
    """Reconstruct the project CRS from a raw .qgs XML string.

    Tries in order: authid (for standard EPSG-like CRS) → wkt → proj4
    (for custom CRS where authid is absent or USER:-scoped).

    Returns an invalid QgsCoordinateReferenceSystem if nothing works.
    """
    doc = QDomDocument()
    doc.setContent(qgisproject_xml)
    srs_el = (
        doc.documentElement()
        .firstChildElement("projectCrs")
        .firstChildElement("spatialrefsys")
    )
    if srs_el.isNull():
        return QgsCoordinateReferenceSystem()

    # Primary: let QGIS handle all nativeFormat/USER:/fallback logic natively
    crs = QgsCoordinateReferenceSystem()
    if crs.readXml(srs_el) and crs.isValid():
        return crs

    # Manual fallbacks for cases where readXml fails
    authid = srs_el.firstChildElement("authid").text()
    if authid and not authid.startswith("USER:"):
        crs = QgsCoordinateReferenceSystem(authid)
        if crs.isValid():
            return crs

    wkt = srs_el.firstChildElement("wkt").text()
    if wkt:
        crs = QgsCoordinateReferenceSystem.fromWkt(wkt)
        if crs.isValid():
            return crs

    proj4 = srs_el.firstChildElement("proj4").text()
    if proj4:
        crs = QgsCoordinateReferenceSystem.fromProj(proj4)
        if crs.isValid():
            return crs

    return QgsCoordinateReferenceSystem()
