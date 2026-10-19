"""Embed local SVG / raster symbol files into the project's symbology.

A symbol layer that references a file on disk stores that path in the .qgs, so the
icon is broken as soon as the project is opened on another machine (the Kumoy web
map is unaffected: it renders from the sprite). QGIS's "Embed file" button stores
the content inline as a ``base64:`` string instead; this module does the same for
every layer of the project.

has_local_symbol_files() only checks, so the caller can ask the user before
embed_local_symbol_files() changes anything. Nothing is carried between the two:
the project is walked again, so no symbol layer is held across the user's answer.
"""

import base64
import os
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


def _iter_symbol_layers(symbol: QgsSymbol) -> Iterator[QgsSymbolLayer]:
    """The symbol's layers, and those of its sub-symbols (e.g. marker lines)."""
    for symbol_layer in symbol.symbolLayers():
        yield symbol_layer
        sub_symbol = symbol_layer.subSymbol()
        if sub_symbol is not None:
            yield from _iter_symbol_layers(sub_symbol)


def _local_file(
    symbol_layer: QgsSymbolLayer, resolver: QgsPathResolver
) -> Optional[str]:
    """The file on this computer that the symbol layer draws, or None."""
    if isinstance(symbol_layer, QgsSvgMarkerSymbolLayer):
        path, is_svg = symbol_layer.path(), True
    elif isinstance(symbol_layer, QgsSVGFillSymbolLayer):
        path, is_svg = symbol_layer.svgFilePath(), True
    elif isinstance(
        symbol_layer, (QgsRasterMarkerSymbolLayer, QgsRasterLineSymbolLayer)
    ):
        path, is_svg = symbol_layer.path(), False
    elif isinstance(symbol_layer, QgsRasterFillSymbolLayer):
        path, is_svg = symbol_layer.imageFilePath(), False
    else:
        return None

    # SVG paths may be bare names relative to the QGIS SVG search paths.
    if is_svg:
        file_path = QgsSymbolLayerUtils.svgSymbolNameToPath(path, resolver)
    else:
        file_path = resolver.readPath(path)
    # isfile() also rules out empty paths, already-embedded content and remote URLs
    # (portable already) without touching the network.
    return file_path if os.path.isfile(file_path) else None


def _local_symbol_files(
    project: QgsProject,
) -> Iterator[tuple[QgsVectorLayer, QgsSymbolLayer, str]]:
    """(layer, symbol layer, local file) for every symbol layer drawing a local file.

    Paths driven by a data-defined override (icon chosen per feature) are not covered:
    only the static fallback path is.
    """
    resolver = QgsPathResolver()
    render_context = QgsRenderContext()
    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer) or layer.renderer() is None:
            continue
        for symbol in layer.renderer().symbols(render_context):
            for symbol_layer in _iter_symbol_layers(symbol):
                file_path = _local_file(symbol_layer, resolver)
                if file_path:
                    yield layer, symbol_layer, file_path


def _read_as_embedded(file_path: str) -> Optional[str]:
    """``base64:`` + the file content, as QGIS's "Embed file" stores it; None (logged)
    if the file cannot be read."""
    try:
        with open(file_path, "rb") as f:
            return "base64:" + base64.b64encode(f.read()).decode("ascii")
    except OSError as e:
        # Info, not Warning: the path stays as is and is retried on every save.
        QgsMessageLog.logMessage(
            f"Could not embed symbol file {file_path}: {e}", LOG_CATEGORY, Qgis.Info
        )
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


def has_local_symbol_files(project: QgsProject) -> bool:
    """Whether any symbol in the project draws an SVG / raster file on this computer.

    Reads no file content and changes nothing.
    """
    return next(_local_symbol_files(project), None) is not None


def embed_local_symbol_files(project: QgsProject) -> None:
    """Replace every local SVG / raster symbol file path with the embedded content.

    Unreadable files keep their path.
    """
    # A categorized renderer often repeats one icon in every category: read it once.
    cache: dict[str, Optional[str]] = {}
    changed_layers: list[QgsVectorLayer] = []
    for layer, symbol_layer, file_path in _local_symbol_files(project):
        if file_path not in cache:
            cache[file_path] = _read_as_embedded(file_path)
        embedded = cache[file_path]
        if embedded is None:
            continue
        _set_file_path(symbol_layer, embedded)
        if layer not in changed_layers:
            changed_layers.append(layer)
    for layer in changed_layers:
        layer.emitStyleChanged()
