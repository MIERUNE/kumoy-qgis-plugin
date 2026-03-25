"""MapLibre Specificationのスプライト生成"""

import json

from qgis.PyQt.QtCore import QBuffer, QByteArray, QSize
from qgis.PyQt.QtGui import QImage, QPainter

from ...pyqt_version import Q_BUFFER_OPEN_MODE, Q_PAINTER_RENDER_HINT

MAX_SPRITE_FILE_SIZE = 1 * 1024 * 1024  # 1MB
SPRITE_ATLAS_MAX_WIDTH = 1024


def _pack_images(
    images: dict[str, QImage],
) -> tuple[dict[str, dict], QImage]:
    """画像をスプライトアトラスにパッキングする。

    Args:
        images: name -> QImage のマッピング

    Returns:
        (sprite_json_dict, atlas_image) のタプル
    """
    if not images:
        return {}, QImage()

    items = list(images.items())
    sprite_json: dict[str, dict] = {}

    # 行ごとにパッキング
    x = 0
    y = 0
    row_height = 0
    total_width = 0
    positions: list[tuple[str, QImage, int, int]] = []

    for name, img in items:
        w = img.width()
        h = img.height()

        if x + w > SPRITE_ATLAS_MAX_WIDTH and x > 0:
            # 次の行へ
            y += row_height
            x = 0
            row_height = 0

        positions.append((name, img, x, y))
        row_height = max(row_height, h)
        x += w
        total_width = max(total_width, x)

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
    return bytes(buf.data())


def _resize_images(images: dict[str, QImage], size: int) -> dict[str, QImage]:
    """画像を指定サイズにリサイズする。"""
    resized = {}
    for name, img in images.items():
        resized[name] = img.scaled(
            QSize(size, size),
        )
    return resized


def generate_sprites(
    symbol_images: dict[str, QImage],
) -> tuple[bytes, bytes]:
    """MapLibreスプライト（sprite.json + sprite.png）を生成する。

    Args:
        symbol_images: name -> QImage のマッピング

    Returns:
        (sprite_json_bytes, sprite_png_bytes) のタプル

    Raises:
        Exception: スプライトサイズが制限を超過した場合
    """
    if not symbol_images:
        empty_json = json.dumps({}).encode("utf-8")
        empty_png = _image_to_png_bytes(QImage(QSize(1, 1), QImage.Format_ARGB32))
        return empty_json, empty_png

    # 64x64でまず試行
    sprite_json, atlas = _pack_images(symbol_images)
    json_bytes = json.dumps(sprite_json).encode("utf-8")
    png_bytes = _image_to_png_bytes(atlas)

    # サイズ超過時は32x32にフォールバック
    if len(json_bytes) > MAX_SPRITE_FILE_SIZE or len(png_bytes) > MAX_SPRITE_FILE_SIZE:
        smaller_images = _resize_images(symbol_images, 32)
        sprite_json, atlas = _pack_images(smaller_images)
        json_bytes = json.dumps(sprite_json).encode("utf-8")
        png_bytes = _image_to_png_bytes(atlas)

    return json_bytes, png_bytes
