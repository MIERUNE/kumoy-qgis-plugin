"""シンボルからスプライト用画像を生成する"""

import math
from dataclasses import dataclass

from qgis.core import (
    Qgis,
    QgsMarkerSymbol,
    QgsProject,
    QgsRenderContext,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QPointF, QRect
from qgis.PyQt.QtGui import QImage, QPainter

from ...pyqt_version import Q_IMAGE_FORMAT
from ..constants import DATA_PROVIDER_KEY

# The web map renders the sprite at its real size, so mm must convert to px the
# same way as the style converter does (convertToPixel in @kumoy-packages/qgisproject)
_PX_PER_MM = 72 / 25.4
# Rendered at this multiple of the display size for HiDPI screens (pixelRatio in sprite.json)
SPRITE_PIXEL_RATIO = 2
# Longest side of a sprite image (px). Larger symbols get a lower pixelRatio, so
# MapLibre upscales them back to their real size
MAX_IMAGE_SIZE = 128
# symbol.bounds() can fall short of the drawn pixels by a fraction of a pixel
_BOUNDS_MARGIN = 2


@dataclass
class SpriteEntry:
    """スプライトアトラスの1エントリ（シンボル単位）"""

    name: str  # {layerID}_{symbolIndex}
    image: QImage
    pixel_ratio: float  # image px per CSS px


def _render_context(painter: QPainter, pixel_ratio: float) -> QgsRenderContext:
    # Scale the painter, not the scaleFactor: the latter leaves Pixel-unit sizes unscaled
    painter.scale(pixel_ratio, pixel_ratio)
    context = QgsRenderContext.fromQPainter(painter)
    context.setScaleFactor(_PX_PER_MM)
    context.setFlag(Qgis.RenderContextFlag.Antialiasing, True)
    # SVG markers are otherwise drawn from an unscaled cached image and come out blurry
    context.setFlag(Qgis.RenderContextFlag.ForceVectorOutput, True)
    return context


def _half_extent(symbol: QgsMarkerSymbol) -> float:
    """アンカーからシンボルの最も遠い端までの距離（CSS px）。"""
    image = QImage(1, 1, Q_IMAGE_FORMAT.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    context = _render_context(painter, 1)
    symbol.startRender(context)
    rect = symbol.bounds(QPointF(0, 0), context)
    symbol.stopRender(context)
    painter.end()
    edges = (rect.left(), rect.right(), rect.top(), rect.bottom())
    return max(abs(edge) for edge in edges) + _BOUNDS_MARGIN


def _render(symbol: QgsMarkerSymbol) -> tuple[QImage, float]:
    """シンボルを実寸でキャンバス中心（＝アンカー）に描画し、画像と pixelRatio を返す。

    一辺が MAX_IMAGE_SIZE に収まるよう、大きいシンボルほど pixelRatio を下げる。
    """
    symbol = symbol.clone()
    # The web map applies the symbol angle as icon-rotate (it may be data-defined),
    # so only the angles of the layers relative to the symbol are baked in
    symbol.setAngle(0)

    half = _half_extent(symbol)
    pixel_ratio = min(SPRITE_PIXEL_RATIO, MAX_IMAGE_SIZE / (2 * half))
    # Even, so that the anchor falls on a pixel boundary as _trim() assumes
    size = min(MAX_IMAGE_SIZE, 2 * math.ceil(half * pixel_ratio))

    image = QImage(size, size, Q_IMAGE_FORMAT.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    context = _render_context(painter, pixel_ratio)
    center = size / pixel_ratio / 2
    symbol.startRender(context)
    symbol.renderPoint(QPointF(center, center), None, context)
    symbol.stopRender(context)
    painter.end()
    return image, pixel_ratio


def _trim(image: QImage) -> QImage:
    """画像中心を保ったまま、透明な余白を切り落とす。"""
    img = image.convertToFormat(Q_IMAGE_FORMAT.Format_ARGB32)
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
        # 完全に透明な画像。MapLibreは画像が無いと警告するので最小の画像を返す
        return image.copy(QRect(0, 0, 1, 1))

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

    # 元画像中心から最も外側のalpha画素までの距離で対称クロップする。
    # 画像中心＝シンボルのアンカーなので、オフセットも回転の中心も保たれる。
    cx = w // 2
    cy = h // 2
    half_w = max(cx - x_min, (x_max + 1) - cx)
    half_h = max(cy - y_min, (y_max + 1) - cy)
    return image.copy(QRect(cx - half_w, cy - half_h, 2 * half_w, 2 * half_h))


def collect_sprites(project: QgsProject) -> list[SpriteEntry]:
    """プロジェクト内の全Pointシンボルからスプライト画像を収集する。"""
    sprites: list[SpriteEntry] = []
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

        # Pointレイヤーのsymbolのみをsprite化する
        if layer.geometryType() != Qgis.GeometryType.Point:
            continue

        for symbol_index, symbol in enumerate(renderer.symbols(render_context)):
            image, pixel_ratio = _render(symbol)
            sprites.append(
                SpriteEntry(
                    name=f"{layer.id()}_{symbol_index}",
                    image=_trim(image),
                    pixel_ratio=pixel_ratio,
                )
            )

    return sprites
