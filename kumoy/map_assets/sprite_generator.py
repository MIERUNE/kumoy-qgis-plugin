"""MapLibre Specificationのスプライト生成"""

import json

from qgis.PyQt.QtCore import QBuffer, QByteArray, QSize
from qgis.PyQt.QtGui import QImage, QPainter

from ...pyqt_version import Q_BUFFER_OPEN_MODE, Q_PAINTER_RENDER_HINT
from .symbol_collector import SpriteEntry

SPRITE_ATLAS_MAX_WIDTH = 1024
SPRITE_PADDING = 2


def _pack_images(
    sprites: list[SpriteEntry],
) -> tuple[dict[str, dict], QImage]:
    """画像をスプライトアトラスにパッキングする。"""
    sprite_json: dict[str, dict] = {}

    # 行ごとにパッキング
    x = 0
    y = 0
    row_height = 0
    total_width = 0
    positions: list[tuple[str, QImage, int, int]] = []

    for entry in sprites:
        img = entry.image
        w = img.width()
        h = img.height()

        if x + w > SPRITE_ATLAS_MAX_WIDTH and x > 0:
            y += row_height + SPRITE_PADDING
            x = 0
            row_height = 0

        positions.append((entry.name, img, x, y))
        row_height = max(row_height, h)
        x += w + SPRITE_PADDING
        total_width = max(total_width, x - SPRITE_PADDING)

    total_height = y + row_height

    if total_width == 0 or total_height == 0:
        return {}, QImage()

    # アトラス画像を描画
    atlas = QImage(QSize(total_width, total_height), QImage.Format_ARGB32_Premultiplied)
    atlas.fill(0)  # 透明

    painter = QPainter(atlas)
    painter.setRenderHint(Q_PAINTER_RENDER_HINT.Antialiasing)

    for name, img, px, py in positions:
        painter.drawImage(px, py, img)
        sprite_json[name] = {
            "width": img.width(),
            "height": img.height(),
            "x": px,
            "y": py,
            "pixelRatio": 1,
        }

    painter.end()

    return sprite_json, atlas


def _image_to_png_bytes(image: QImage) -> bytes:
    """QImageをPNGバイト列に変換する。"""
    buf = QBuffer()
    buf.open(Q_BUFFER_OPEN_MODE.WriteOnly)
    image.save(buf, "PNG")
    buf.close()
    return bytes(buf.data())


def generate_sprites(
    sprites: list[SpriteEntry],
) -> tuple[bytes, bytes]:
    """MapLibreスプライト（sprite.json + sprite.png）を生成する。

    Args:
        sprites: SpriteEntryのリスト

    Returns:
        (sprite_json_bytes, sprite_png_bytes) のタプル
    """
    sprite_json, atlas = _pack_images(sprites)
    json_bytes = json.dumps(sprite_json).encode("utf-8")
    png_bytes = _image_to_png_bytes(atlas)
    return json_bytes, png_bytes
