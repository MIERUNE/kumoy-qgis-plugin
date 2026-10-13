"""Build QGIS project files that reference Kumoy layers, for tests.

A real Kumoy layer needs the server, so a memory layer is saved first and its
provider and datasource are rewritten in the XML.
"""

import re
import zipfile
from pathlib import Path

from qgis.core import (
    QgsMarkerSymbol,
    QgsProject,
    QgsSingleSymbolRenderer,
    QgsSvgMarkerSymbolLayer,
    QgsVectorLayer,
)

# 20x10 so that its default aspect ratio (height / width) is 0.5
SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10">'
    '<rect width="20" height="10" fill="red"/></svg>'
)


def write_kumoy_point_project(directory: Path) -> Path:
    """Write a .qgs with one Kumoy point layer using an SVG marker."""
    svg_path = directory / "marker.svg"
    svg_path.write_text(SVG, encoding="utf-8")

    layer = QgsVectorLayer("Point?crs=EPSG:4326", "points", "memory")
    symbol = QgsMarkerSymbol()
    symbol.changeSymbolLayer(0, QgsSvgMarkerSymbolLayer(str(svg_path), 10))
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))

    project = QgsProject()
    project.addMapLayer(layer)
    path = directory / "project.qgs"
    project.write(str(path))

    xml = path.read_text(encoding="utf-8")
    xml = re.sub(
        r"<provider([^>]*)>memory</provider>", r"<provider\1>kumoy</provider>", xml
    )
    xml = re.sub(
        r"<datasource>[^<]+</datasource>",
        "<datasource>project_id=p1;vector_id=v1;vector_name=points;"
        "vector_type=POINT;</datasource>",
        xml,
    )
    path.write_text(xml, encoding="utf-8")
    return path


def to_qgz(qgs_path: Path) -> Path:
    qgz_path = qgs_path.with_suffix(".qgz")
    with zipfile.ZipFile(qgz_path, "w") as archive:
        archive.write(qgs_path, qgs_path.name)
    return qgz_path


def fixed_aspect_ratios(qgisproject: str) -> list:
    return re.findall(
        r'value="([^"]*)"',
        " ".join(re.findall(r'<Option[^>]*name="fixedAspectRatio"[^>]*>', qgisproject)),
    )
