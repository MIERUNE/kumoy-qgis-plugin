"""シンボルからファイル参照を収集し、スプライト用画像を生成する"""

import os
from dataclasses import dataclass
from typing import Optional

from qgis.core import (
    Qgis,
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
from qgis.PyQt.QtCore import QRect, QSize, Qt
from qgis.PyQt.QtGui import QImage

from ..constants import DATA_PROVIDER_KEY


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


def _get_file_path_from_symbol_layer(symbol_layer: QgsSymbolLayer) -> Optional[str]:
    """シンボルレイヤーからファイルパスを取得する"""
    if isinstance(symbol_layer, (QgsSvgMarkerSymbolLayer, QgsRasterMarkerSymbolLayer)):
        return symbol_layer.path()

    if isinstance(symbol_layer, QgsSVGFillSymbolLayer):
        return symbol_layer.svgFilePath()

    if isinstance(symbol_layer, QgsRasterFillSymbolLayer):
        return symbol_layer.imageFilePath()

    return None


def _trim_and_fit(image: QImage, max_size: int) -> QImage:
    """画像の透明余白をトリムし、max_size x max_size 内にフィットさせる。"""
    img = image.convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()
    stride = img.bytesPerLine()
    ptr = img.constBits()
    buf = ptr.asstring(stride * h)

    # 外周から走査してalpha非ゼロの最外縁を求める（ARGB32: B,G,R,A の順で4バイト）
    def _has_alpha_in_row(y: int) -> bool:
        row_offset = y * stride
        return any(buf[row_offset + x * 4 + 3] for x in range(w))

    def _has_alpha_in_col(x: int) -> bool:
        return any(buf[y * stride + x * 4 + 3] for y in range(h))

    # 上端から下へ走査
    y_min = 0
    while y_min < h and not _has_alpha_in_row(y_min):
        y_min += 1

    if y_min == h:
        # 完全に透明な画像
        return image.scaled(
            QSize(max_size, max_size), Qt.KeepAspectRatio, Qt.FastTransformation
        )

    # 下端から上へ走査
    y_max = h - 1
    while y_max > y_min and not _has_alpha_in_row(y_max):
        y_max -= 1

    # 左端から右へ走査
    x_min = 0
    while x_min < w and not _has_alpha_in_col(x_min):
        x_min += 1

    # 右端から左へ走査
    x_max = w - 1
    while x_max > x_min and not _has_alpha_in_col(x_max):
        x_max -= 1

    cropped = image.copy(QRect(x_min, y_min, x_max - x_min + 1, y_max - y_min + 1))

    # 高さを max_size に合わせてスケーリング（アスペクト比維持）
    cw, ch = cropped.width(), cropped.height()
    if ch > 0:
        scale = max_size / ch
        target = QSize(round(cw * scale), round(ch * scale))
    else:
        target = QSize(max_size, max_size)
    return cropped.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)


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

        # kumoy only
        if layer.dataProvider().name() != DATA_PROVIDER_KEY:
            continue

        renderer = layer.renderer()
        if renderer is None:
            continue

        for symbol_index, symbol in enumerate(renderer.symbols(render_context)):
            # Pointレイヤーのsymbolのみをsprite化する
            if layer.geometryType() == Qgis.GeometryType.Point:
                raw_image = symbol.asImage(QSize(128, 128))
                if raw_image and not raw_image.isNull():
                    image = _trim_and_fit(raw_image, 48)
                    sprite_name = f"{layer.id()}_{symbol_index}"
                    sprites.append(SpriteEntry(name=sprite_name, image=image))

            # ファイル: シンボルレイヤー単位で収集
            for i in range(symbol.symbolLayerCount()):
                sl = symbol.symbolLayer(i)
                raw_path = _get_file_path_from_symbol_layer(sl)

                if raw_path is None or raw_path.startswith(("http://", "https://")):
                    # ローカルファイルに依存していない場合
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
