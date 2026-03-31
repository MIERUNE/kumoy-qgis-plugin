"""QGSプロジェクトのシンボルレイヤーパスを書き換える"""

import os
import shutil

from qgis.core import (
    QgsApplication,
    QgsProject,
    QgsRasterFillSymbolLayer,
    QgsRasterMarkerSymbolLayer,
    QgsRenderContext,
    QgsSVGFillSymbolLayer,
    QgsSvgMarkerSymbolLayer,
    QgsSymbolLayer,
    QgsVectorLayer,
)

from .symbol_collector import FileAsset


def _set_file_path(symbol_layer: QgsSymbolLayer, path: str) -> None:
    """シンボルレイヤーにファイルパスを設定する。"""
    if isinstance(symbol_layer, (QgsSvgMarkerSymbolLayer, QgsRasterMarkerSymbolLayer)):
        symbol_layer.setPath(path)
    elif isinstance(symbol_layer, QgsSVGFillSymbolLayer):
        symbol_layer.setSvgFilePath(path)
    elif isinstance(symbol_layer, QgsRasterFillSymbolLayer):
        symbol_layer.setImageFilePath(path)


def rewrite_paths(project: QgsProject, files: list[FileAsset], assets_dir: str) -> None:
    """シンボルレイヤーのパスを相対パスに書き換え、ファイルをコピーする。"""
    path_map: dict[str, str] = {}
    svgCache = QgsApplication.svgCache()
    imageCache = QgsApplication.imageCache()
    assert svgCache is not None
    assert imageCache is not None

    for asset in files:
        svgCache.invalidateCacheEntry(asset.original_path)
        imageCache.invalidateCacheEntry(asset.original_path)

        dest_name = f"{asset.symbol_layer_id}{asset.ext}"
        dest_path = os.path.join(assets_dir, dest_name)
        if os.path.abspath(asset.original_path) != os.path.abspath(dest_path):
            shutil.copy2(asset.original_path, dest_path)
        path_map[asset.symbol_layer_id] = f"./assets/{dest_name}"

    render_context = QgsRenderContext()
    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue
        renderer = layer.renderer()
        if renderer is None:
            continue

        for symbol in renderer.symbols(render_context):
            for i in range(symbol.symbolLayerCount()):
                sl = symbol.symbolLayer(i)

                if sl.id() in path_map:
                    _set_file_path(sl, path_map[sl.id()])
