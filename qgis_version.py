from typing import Optional
from urllib.parse import unquote

from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsMessageLog, QgsProject
from qgis.PyQt.QtXml import QDomDocument


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


def fix_xyz_layer_datasources() -> None:
    """Fix XYZ tile layer datasources that became broken
    after loading a QGIS 4 project in QGIS 3.
    """
    project = QgsProject.instance()
    fixed_count = 0
    for layer in project.mapLayers().values():
        if layer.providerType() != "wms":
            continue
        source = layer.source()
        if "type=xyz" not in source:
            continue
        fixed = _fix_xyz_datasource(source)
        if fixed is None:
            continue
        layer.setDataSource(fixed, layer.name(), "wms")
        fixed_count += 1

    if fixed_count > 0:
        QgsMessageLog.logMessage(
            f"Fixed {fixed_count} XYZ layer datasource(s) for QGIS 3 compatibility",
            "Kumoy",
            Qgis.Warning,
        )


def _fix_xyz_datasource(datasource: str) -> Optional[str]:
    """Convert a QGIS 4 XYZ datasource string to QGIS 3 compatible format.

    QGIS 4 percent-encodes the tile URL (url=https%3A%2F%2F...) while QGIS 3
    expects a plain URL (url=https://...).

    Returns None if no fix is needed (already in QGIS 3 format).
    """
    if "url=https%3A" not in datasource and "url=http%3A" not in datasource:
        return None

    params: dict[str, str] = {}
    for part in datasource.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            params[k] = v
        else:
            params[part] = ""

    url = unquote(params.get("url", ""))
    zmin = params.get("zmin", "0")
    zmax = params.get("zmax", "18")
    referer = params.get("http-header:referer", "")

    return f"http-header:referer={referer}&type=xyz&url={url}&zmax={zmax}&zmin={zmin}"
