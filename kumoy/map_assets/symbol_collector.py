"""シンボルからスプライト用画像を生成する"""

from dataclasses import dataclass

from qgis.core import (
    Qgis,
    QgsProject,
    QgsRenderContext,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QRect, QSize
from qgis.PyQt.QtGui import QImage, QPainter

from ...pyqt_version import Q_IMAGE_FORMAT, QT_ASPECT_RATIO_MODE, QT_TRANSFORMATION_MODE
from ..constants import DATA_PROVIDER_KEY


@dataclass
class SpriteEntry:
    """スプライトアトラスの1エントリ（シンボル単位）"""

    name: str  # {layerID}_{symbolIndex}
    image: QImage


_SPRITE_MARGIN = 1
"""スプライト外周に設ける透明マージンの幅（px）。

MapLibreがバイリニアフィルタで境界ピクセルをサンプリングする際に、
アトラス内の隣接ピクセルを巻き込んで境界がにじむのを防ぐため、
各スプライトの周囲に必ず透明ピクセルを残す。
"""


def _trim_and_fit(image: QImage, max_size: int) -> QImage:
    """画像の透明余白をトリムし、シンボル高さが max_size となるようスケールする。

    クライアント側は「QGISシンボル高さ / max_size」を MapLibre の icon-size と
    するため、スプライト内のシンボル高さは必ず max_size に一致する必要がある。
    幅はシンボルのアスペクトに応じて可変。

    四辺には _SPRITE_MARGIN px の透明余白を確保する。MapLibre のバイリニア
    フィルタがアトラス内の隣接ピクセルを巻き込み境界がにじむのを防ぐため。
    """
    img = image.convertToFormat(Q_IMAGE_FORMAT.Format_ARGB32)
    w, h = img.width(), img.height()
    stride = img.bytesPerLine()
    ptr = img.constBits()
    buf = ptr.asstring(stride * h)

    # 外周から走査して alpha 非ゼロの最外縁を求める（ARGB32: B,G,R,A の順で4バイト）
    def _has_alpha_in_row(y: int) -> bool:
        row_offset = y * stride
        return any(buf[row_offset + x * 4 + 3] for x in range(w))

    def _has_alpha_in_col(x: int) -> bool:
        return any(buf[y * stride + x * 4 + 3] for y in range(h))

    y_min = 0
    while y_min < h and not _has_alpha_in_row(y_min):
        y_min += 1

    if y_min == h:
        # 完全に透明な画像：max_size x max_size の透明キャンバスを返す
        canvas = QImage(QSize(max_size, max_size), Q_IMAGE_FORMAT.Format_ARGB32)
        canvas.fill(0)
        return canvas

    y_max = h - 1
    while y_max > y_min and not _has_alpha_in_row(y_max):
        y_max -= 1

    x_min = 0
    while x_min < w and not _has_alpha_in_col(x_min):
        x_min += 1

    x_max = w - 1
    while x_max > x_min and not _has_alpha_in_col(x_max):
        x_max -= 1

    cropped = image.copy(QRect(x_min, y_min, x_max - x_min + 1, y_max - y_min + 1))
    cw, ch = cropped.width(), cropped.height()

    # 描画領域の高さ = max_size - 2*margin。高さ基準でスケール。
    inner_size = max(1, max_size - 2 * _SPRITE_MARGIN)
    scale = inner_size / ch if ch > 0 else 1.0
    scaled_w = max(1, round(cw * scale))  # 0pxとなることを避ける
    scaled_h = max(1, round(ch * scale))
    scaled = cropped.scaled(
        QSize(scaled_w, scaled_h),
        QT_ASPECT_RATIO_MODE.KeepAspectRatio,
        QT_TRANSFORMATION_MODE.SmoothTransformation,
    )

    # 左右にも _SPRITE_MARGIN px のマージンを付与。高さは max_size に固定。
    canvas_width = scaled.width() + 2 * _SPRITE_MARGIN
    canvas = QImage(QSize(canvas_width, max_size), Q_IMAGE_FORMAT.Format_ARGB32)
    canvas.fill(0)
    pad_top = (max_size - scaled.height()) // 2
    painter = QPainter(canvas)
    painter.drawImage(_SPRITE_MARGIN, pad_top, scaled)
    painter.end()
    return canvas


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
            raw_image = symbol.asImage(QSize(256, 256))
            if raw_image and not raw_image.isNull():
                image = _trim_and_fit(raw_image, 64)
                sprite_name = f"{layer.id()}_{symbol_index}"
                sprites.append(SpriteEntry(name=sprite_name, image=image))

    return sprites
