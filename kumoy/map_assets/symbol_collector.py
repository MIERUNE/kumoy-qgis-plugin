"""シンボルからスプライト用画像を生成する"""

from dataclasses import dataclass

from qgis.core import (
    Qgis,
    QgsProject,
    QgsRenderContext,
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
            QSize(max_size, max_size), Qt.KeepAspectRatio, Qt.SmoothTransformation
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

    # 縦幅を max_size に合わせて縮小（アスペクト比維持）
    cw, ch = cropped.width(), cropped.height()
    if ch > 0:
        scale = max_size / ch
        target = QSize(round(cw * scale), round(ch * scale))
    else:
        target = QSize(max_size, max_size)
    return cropped.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)


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
