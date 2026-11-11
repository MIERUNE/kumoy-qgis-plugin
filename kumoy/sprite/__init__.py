import hashlib
from dataclasses import dataclass
from typing import Optional

from qgis.core import QgsProject

from .sprite_packer import pack_sprites
from .symbol_collector import collect_sprites
from .symbol_embedder import embed_local_symbol_files, embedding_size_increase
from .symbol_normalizer import pin_fixed_aspect_ratios

__all__ = [
    "SpriteData",
    "embed_local_symbol_files",
    "embedding_size_increase",
    "generate_sprite",
    "pin_fixed_aspect_ratios",
]


# Keep in sync with REAL_SIZE_SPRITE_PREFIX in @kumoy-packages/qgisproject
SPRITE_FORMAT_PREFIX = "v2-"


@dataclass
class SpriteData:
    json_bytes: bytes
    png_bytes: bytes
    assets_hash: str


def generate_sprite(project: QgsProject) -> Optional[SpriteData]:
    """スプライトを生成しハッシュ値を計算する。

    ハッシュ値のチェックやアップロード（api 依存）は呼び出し元 / uploader で行う。
    """
    sprites = collect_sprites(project)
    if not sprites:
        return None

    json_bytes, png_bytes = pack_sprites(sprites)
    # The prefix tells the web map that the sprite is drawn at its real size with
    # no rotation baked in (older sprites are scaled to 64 px with the angle baked)
    assets_hash = (
        SPRITE_FORMAT_PREFIX + hashlib.sha256(json_bytes + png_bytes).hexdigest()
    )

    return SpriteData(
        json_bytes=json_bytes, png_bytes=png_bytes, assets_hash=assets_hash
    )
