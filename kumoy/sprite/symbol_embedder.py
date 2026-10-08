"""Embed local SVG / raster symbol files into the serialized project at save time.

A symbol layer that references a file on disk stores that path in the .qgs, so the
icon is broken as soon as the project is opened on another machine (the Kumoy web
map is unaffected: it renders from the sprite). QGIS's "Embed file" button stores
the content inline as a ``base64:`` string instead; this module does the same on the
serialized .qgs automatically.

WHY the XML and not the symbol layers: setPath() resets an SVG's fill/stroke to its
own defaults (so each setter would need a save/restore dance), and one pass over the
XML also reaches every symbol (sub-symbols, categories, rules) without walking the
renderers.
"""

import base64
import os
from typing import Optional

from qgis.core import Qgis, QgsMessageLog, QgsPathResolver, QgsSymbolLayerUtils
from qgis.PyQt.QtXml import QDomDocument

from ..constants import LOG_CATEGORY

EMBEDDED_PREFIX = "base64:"

# <layer class="..."> in the .qgs -> (name of the <Option> holding the path, is it SVG).
# SVG paths may be bare names relative to the QGIS SVG search paths.
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
        # Info, not Warning: this runs on every save and a broken path stays broken.
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


def embed_symbol_files(qgs: str, project_path: str) -> str:
    """Return ``qgs`` with the files of SVG / raster symbols embedded as ``base64:``.

    ``project_path`` is the file the project was written to: relative paths in the
    XML are relative to its directory. Already-embedded, remote, missing and empty
    paths are left untouched. ``qgs`` is returned as is when nothing was embedded
    (or when it cannot be parsed), so the call is idempotent.

    Every file-based symbol layer is covered, but paths driven by a data-defined
    override (icon chosen per feature) are not: only the static fallback path is.
    """
    doc = QDomDocument()
    doc.setContent(qgs)
    resolver = QgsPathResolver(project_path)
    cache: dict[str, Optional[str]] = {}
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

    return doc.toString(2) if changed else qgs
