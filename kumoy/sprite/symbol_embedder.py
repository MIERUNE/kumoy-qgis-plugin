"""Embed local SVG / raster symbol files into the project's symbology.

A symbol layer that references a file on disk stores that path in the .qgs, so the
icon is broken as soon as the project is opened on another machine (the Kumoy web
map is unaffected: it renders from the sprite). QGIS's "Embed file" button stores
the content inline as a ``base64:`` string instead; this module does the same for
every layer of the project.

Embedding is split in two steps, prepare then apply, so the caller can ask the user
in between: prepare_symbol_embedding() changes nothing.
"""

import base64
from typing import Iterator, Optional

from qgis.core import (
    Qgis,
    QgsMessageLog,
    QgsPathResolver,
    QgsProject,
    QgsRasterFillSymbolLayer,
    QgsRasterLineSymbolLayer,
    QgsRasterMarkerSymbolLayer,
    QgsRenderContext,
    QgsSVGFillSymbolLayer,
    QgsSvgMarkerSymbolLayer,
    QgsSymbol,
    QgsSymbolLayer,
    QgsSymbolLayerUtils,
    QgsVectorLayer,
)

from ..constants import LOG_CATEGORY

_EMBEDDED_PREFIX = "base64:"


def file_to_embedded_path(file_path: str) -> str:
    """Return the file content as an embedded path: ``base64:`` + the base64 data.

    This is what QGIS's "Embed file" button stores in a symbol layer instead of a
    path. The prefix and the encoding live together here, with is_embedded_path()
    as the matching check. Raises OSError if the file cannot be read.
    """
    with open(file_path, "rb") as f:
        return _EMBEDDED_PREFIX + base64.b64encode(f.read()).decode("ascii")


def is_embedded_path(path: str) -> bool:
    """Whether ``path`` is already embedded content (see file_to_embedded_path)."""
    return path.startswith(_EMBEDDED_PREFIX)


def _read_as_embedded(file_path: str) -> Optional[str]:
    """Embedded form of the file, or None (logged) if it cannot be read."""
    try:
        return file_to_embedded_path(file_path)
    except OSError as e:
        # Info, not Warning: a broken path stays broken and is retried on every save.
        QgsMessageLog.logMessage(
            f"Could not embed symbol file {file_path}: {e}", LOG_CATEGORY, Qgis.Info
        )
        return None


def _embedded_value(
    path: str,
    is_svg: bool,
    resolver: QgsPathResolver,
    cache: dict[str, Optional[str]],
) -> Optional[str]:
    """Return the embedded replacement for ``path``, or None to leave it as is."""
    if not path or is_embedded_path(path):
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


def _iter_symbol_layers(symbol: QgsSymbol) -> Iterator[QgsSymbolLayer]:
    """The symbol's layers, and those of its sub-symbols (e.g. marker lines)."""
    for symbol_layer in symbol.symbolLayers():
        yield symbol_layer
        sub_symbol = symbol_layer.subSymbol()
        if sub_symbol is not None:
            yield from _iter_symbol_layers(sub_symbol)


def _file_path(symbol_layer: QgsSymbolLayer) -> Optional[tuple[str, bool]]:
    """(path, is_svg) of a file-based symbol layer; None for any other kind.

    is_svg is False for raster images. SVG paths may be bare names relative to the
    QGIS SVG search paths, so they are resolved differently from raster file paths.
    """
    if isinstance(symbol_layer, QgsSvgMarkerSymbolLayer):
        return symbol_layer.path(), True
    if isinstance(symbol_layer, QgsSVGFillSymbolLayer):
        return symbol_layer.svgFilePath(), True
    if isinstance(symbol_layer, (QgsRasterMarkerSymbolLayer, QgsRasterLineSymbolLayer)):
        return symbol_layer.path(), False
    if isinstance(symbol_layer, QgsRasterFillSymbolLayer):
        return symbol_layer.imageFilePath(), False
    return None


def _set_file_path(symbol_layer: QgsSymbolLayer, path: str) -> None:
    # For SVGs, setPath() / setSvgFilePath() reset fill/stroke to the file's own
    # defaults: put the user's back.
    if isinstance(symbol_layer, QgsSvgMarkerSymbolLayer):
        fill = symbol_layer.fillColor()
        stroke = symbol_layer.strokeColor()
        stroke_width = symbol_layer.strokeWidth()
        symbol_layer.setPath(path)
        symbol_layer.setFillColor(fill)
        symbol_layer.setStrokeColor(stroke)
        symbol_layer.setStrokeWidth(stroke_width)
    elif isinstance(symbol_layer, QgsSVGFillSymbolLayer):
        fill = symbol_layer.svgFillColor()
        stroke = symbol_layer.svgStrokeColor()
        stroke_width = symbol_layer.svgStrokeWidth()
        symbol_layer.setSvgFilePath(path)
        symbol_layer.setSvgFillColor(fill)
        symbol_layer.setSvgStrokeColor(stroke)
        symbol_layer.setSvgStrokeWidth(stroke_width)
    elif isinstance(symbol_layer, QgsRasterFillSymbolLayer):
        symbol_layer.setImageFilePath(path)
    else:
        symbol_layer.setPath(path)


def prepare_symbol_embedding(
    project: QgsProject,
) -> dict[QgsVectorLayer, list[tuple[QgsSymbolLayer, str]]]:
    """Work out, without changing anything, which symbol files to embed.

    Returns, for each vector layer that references SVG / raster files on disk, the
    symbol layers to update with their embedded content; layers with nothing to embed
    are left out, so an empty result means there is nothing to do. Missing or
    unreadable files, remote images and already-embedded ones are not counted.

    Paths driven by a data-defined override (icon chosen per feature) are not covered:
    only the static fallback path is.
    """
    resolver = QgsPathResolver()
    cache: dict[str, Optional[str]] = {}
    render_context = QgsRenderContext()
    changes: dict[QgsVectorLayer, list[tuple[QgsSymbolLayer, str]]] = {}

    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer) or layer.renderer() is None:
            continue
        for symbol in layer.renderer().symbols(render_context):
            for symbol_layer in _iter_symbol_layers(symbol):
                file = _file_path(symbol_layer)
                if file is None:
                    continue
                embedded = _embedded_value(*file, resolver, cache)
                if embedded is not None:
                    changes.setdefault(layer, []).append((symbol_layer, embedded))

    return changes


def apply_symbol_embedding(
    changes: dict[QgsVectorLayer, list[tuple[QgsSymbolLayer, str]]],
) -> None:
    """Embed the files, as worked out by prepare_symbol_embedding()."""
    for layer, layer_changes in changes.items():
        for symbol_layer, embedded in layer_changes:
            _set_file_path(symbol_layer, embedded)
        layer.emitStyleChanged()
