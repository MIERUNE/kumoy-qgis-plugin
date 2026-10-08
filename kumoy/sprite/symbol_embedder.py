"""Embed local SVG / raster symbol files into the project's symbology.

A symbol layer that references a file on disk stores that path in the .qgs, so the
icon is broken as soon as the project is opened on another machine (the Kumoy web
map is unaffected: it renders from the sprite). QGIS's "Embed file" button stores
the content inline as a ``base64:`` string instead; this module does the same for
every layer of the project.

Embedding is split in two steps, prepare then apply, so the caller can ask the user
in between: prepare_symbol_embedding() changes nothing.

WHY the style XML and not the symbol layers: setPath() resets an SVG's fill/stroke to
its own defaults (so each setter would need a save/restore dance), and one pass over
the XML also reaches every symbol (sub-symbols, categories, rules) without walking the
renderers.
"""

import base64
from typing import Optional

from qgis.core import (
    Qgis,
    QgsMapLayer,
    QgsMessageLog,
    QgsPathResolver,
    QgsProject,
    QgsSymbolLayerUtils,
    QgsVectorLayer,
)
from qgis.PyQt.QtXml import QDomDocument

from ..constants import LOG_CATEGORY

EMBEDDED_PREFIX = "base64:"

_SYMBOLOGY = QgsMapLayer.StyleCategory.Symbology

# <layer class="..."> in the style XML -> (name of the <Option> holding the path, is_svg).
# is_svg is False for raster images. SVG paths may be bare names relative to the QGIS
# SVG search paths, so they are resolved differently from plain raster file paths.
_FILE_OPTIONS = {
    "SvgMarker": ("name", True),
    "SVGFill": ("svgFile", True),
    "RasterMarker": ("imageFile", False),
    "RasterFill": ("imageFile", False),
    "RasterLine": ("imageFile", False),
}


def _read_as_embedded(file_path: str) -> Optional[str]:
    """Return the file content as a ``base64:`` string, or None if unreadable."""
    try:
        with open(file_path, "rb") as f:
            data = f.read()
    except OSError as e:
        # Info, not Warning: a broken path stays broken and is retried on every save.
        QgsMessageLog.logMessage(
            f"Could not embed symbol file {file_path}: {e}", LOG_CATEGORY, Qgis.Info
        )
        return None
    return EMBEDDED_PREFIX + base64.b64encode(data).decode("ascii")


def _embedded_value(
    path: str,
    is_svg: bool,
    resolver: QgsPathResolver,
    cache: dict[str, Optional[str]],
) -> Optional[str]:
    """Return the ``base64:`` replacement for ``path``, or None to leave it as is."""
    if not path or path.startswith(EMBEDDED_PREFIX):
        return None
    # Remote images are portable already, and fetching them here would block the save.
    if path.lower().startswith(("http://", "https://")):
        return None

    if is_svg:
        file_path = QgsSymbolLayerUtils.svgSymbolNameToPath(path, resolver)
    else:
        file_path = resolver.readPath(path)
    if not file_path:
        return None

    # A categorized renderer often repeats one icon in every category: read it once.
    if file_path not in cache:
        cache[file_path] = _read_as_embedded(file_path)
    return cache[file_path]


def _embed_in_document(
    doc: QDomDocument,
    resolver: QgsPathResolver,
    cache: dict[str, Optional[str]],
) -> bool:
    """Embed the files of the SVG / raster symbols of ``doc``. True if any changed."""
    changed = False

    layers = doc.elementsByTagName("layer")
    for i in range(layers.count()):
        layer = layers.at(i).toElement()
        spec = _FILE_OPTIONS.get(layer.attribute("class"))
        if spec is None:
            continue
        key, is_svg = spec

        options = layer.firstChildElement("Option").childNodes()
        for j in range(options.count()):
            option = options.at(j).toElement()
            if option.attribute("name") != key:
                continue
            embedded = _embedded_value(
                option.attribute("value"), is_svg, resolver, cache
            )
            if embedded is not None:
                option.setAttribute("value", embedded)
                changed = True
            break

    return changed


def prepare_symbol_embedding(project: QgsProject) -> dict[QgsVectorLayer, QDomDocument]:
    """Compute, without changing anything, the symbology to embed local symbol files.

    Returns, for each vector layer that references SVG / raster files on disk, its
    symbology style XML with those files embedded; layers with nothing to embed are
    left out, so an empty result means there is nothing to do. Missing or unreadable
    files, remote images and already-embedded ones are not counted.

    Paths driven by a data-defined override (icon chosen per feature) are not covered:
    only the static fallback path is.
    """
    resolver = QgsPathResolver()
    cache: dict[str, Optional[str]] = {}
    styles: dict[QgsVectorLayer, QDomDocument] = {}

    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue
        doc = QDomDocument()
        layer.exportNamedStyle(doc, categories=_SYMBOLOGY)
        if _embed_in_document(doc, resolver, cache):
            styles[layer] = doc

    return styles


def apply_symbol_embedding(styles: dict[QgsVectorLayer, QDomDocument]) -> None:
    """Replace the symbology of the layers with what prepare_symbol_embedding() built."""
    for layer, doc in styles.items():
        ok, error = layer.importNamedStyle(doc, categories=_SYMBOLOGY)
        if not ok:
            QgsMessageLog.logMessage(
                f"Could not embed symbol files of layer '{layer.name()}': {error}",
                LOG_CATEGORY,
                Qgis.Warning,
            )
