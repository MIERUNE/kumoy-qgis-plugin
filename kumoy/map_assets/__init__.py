import hashlib
from dataclasses import dataclass
from typing import Optional

from qgis.core import QgsProject

from .. import api
from .sprite_packer import pack_sprites
from .symbol_collector import collect_sprites
from .symbol_normalizer import pin_fixed_aspect_ratios
from .uploader import upload_to_presigned_url


@dataclass
class SpriteData:
    json_bytes: bytes
    png_bytes: bytes
    assets_hash: str


def generate_sprite(project: QgsProject) -> Optional[SpriteData]:
    """スプライトを生成しハッシュ値を計算する。

    ハッシュ値のチェックやアップロードは呼び出し元で行う。
    """
    sprites = collect_sprites(project)
    if not sprites:
        return None

    json_bytes, png_bytes = pack_sprites(sprites)
    assets_hash = hashlib.sha256(json_bytes + png_bytes).hexdigest()

    return SpriteData(
        json_bytes=json_bytes, png_bytes=png_bytes, assets_hash=assets_hash
    )


def upload_sprites(styled_map_id: str, sprite_data: SpriteData) -> None:
    """スプライトをpresigned URLにアップロードする。"""
    upload_urls = api.styledmap.get_sprite_upload_urls(
        styled_map_id,
        len(sprite_data.json_bytes),
        len(sprite_data.png_bytes),
    )
    server_url = api.config.get_api_config().SERVER_URL
    upload_to_presigned_url(
        url=f"{server_url}{upload_urls.json.url}",
        fields=upload_urls.json.fields,
        filename=upload_urls.json.filename,
        file_data=sprite_data.json_bytes,
        content_type="application/json",
    )
    upload_to_presigned_url(
        url=f"{server_url}{upload_urls.png.url}",
        fields=upload_urls.png.fields,
        filename=upload_urls.png.filename,
        file_data=sprite_data.png_bytes,
        content_type="image/png",
    )
