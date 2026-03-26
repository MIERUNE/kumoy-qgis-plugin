"""シンボルからファイル参照を収集し、スプライト用画像を生成する"""

import os
from dataclasses import dataclass

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
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QImage


@dataclass
class SpriteEntry:
    """スプライトアトラスの1エントリ（シンボル単位）"""

    name: str  # {layerID}_{symbolIndex}
    image: QImage


@dataclass
class FileAsset:
    """シンボルレイヤーが参照するファイル（シンボルレイヤー単位）"""

    symbol_layer_id: str  # シンボルレイヤーID
    original_path: str  # 元の絶対パス
    ext: str  # 拡張子（.svg, .png 等）


@dataclass
class CollectedAssets:
    """収集結果"""

    sprites: list[SpriteEntry]
    files: list[FileAsset]


def _get_file_path_from_symbol_layer(symbol_layer: QgsSymbolLayer) -> str:
    """シンボルレイヤーからファイルパスを取得する"""
    if isinstance(symbol_layer, (QgsSvgMarkerSymbolLayer, QgsRasterMarkerSymbolLayer)):
        return symbol_layer.path()

    if isinstance(symbol_layer, QgsSVGFillSymbolLayer):
        return symbol_layer.svgFilePath()

    if isinstance(symbol_layer, QgsRasterFillSymbolLayer):
        return symbol_layer.imageFilePath()

    raise NotImplementedError(f"Unsupported symbol layer type: {type(symbol_layer)}")


def _resolve_svg_path(path: str) -> str:
    """SVGパスを絶対パスに解決する。
    QGISのSVGサーチパスを考慮して相対パスを解決する。
    """
    if os.path.isabs(path) and os.path.isfile(path):
        return path

    # QGISのSVGサーチパスから探す
    for svg_dir in QgsApplication.svgPaths():
        full_path = os.path.join(svg_dir, path)
        if os.path.isfile(full_path):
            return full_path

    return path


def collect_assets(project: QgsProject) -> CollectedAssets:
    """プロジェクト内の全シンボルからスプライト画像とファイル参照を収集する。

    スプライトはシンボル単位（{layerID}_{symbolIndex}）、
    ファイルはシンボルレイヤー単位（{symbolLayerID}）で収集する。
    """
    sprites: list[SpriteEntry] = []
    files: list[FileAsset] = []
    render_context = QgsRenderContext()

    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue

        renderer = layer.renderer()
        if renderer is None:
            continue

        layer_id = layer.id()

        for symbol_index, symbol in enumerate(renderer.symbols(render_context)):
            # スプライト: シンボル単位で画像生成
            image = symbol.asImage(QSize(64, 64))
            if image and not image.isNull():
                sprite_name = f"{layer_id}_{symbol_index}"
                sprites.append(SpriteEntry(name=sprite_name, image=image))

            # ファイル: シンボルレイヤー単位で収集
            for i in range(symbol.symbolLayerCount()):
                sl = symbol.symbolLayer(i)
                raw_path = _get_file_path_from_symbol_layer(sl)
                if raw_path.startswith(("http://", "https://")):
                    continue

                resolved = _resolve_svg_path(raw_path)
                if os.path.isfile(resolved):
                    ext = os.path.splitext(resolved)[1]
                    files.append(
                        FileAsset(
                            symbol_layer_id=sl.id(),
                            original_path=resolved,
                            ext=ext,
                        )
                    )

    return CollectedAssets(sprites=sprites, files=files)
