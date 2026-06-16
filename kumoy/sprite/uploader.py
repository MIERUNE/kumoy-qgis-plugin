"""スプライトを presigned URL にアップロードする（api 依存の処理）。

sprite パッケージ本体（``__init__``）が ``api`` を import すると、
``sprite -> api -> local_cache.map -> sprite`` の循環参照になる。
api を使うのはアップロードだけなので、ここに分離してパッケージ本体を
api 非依存に保つ。
"""

from .. import api
from ..upload.presigned import upload_bytes_to_presigned_post
from . import SpriteData


def upload_sprites(styled_map_id: str, sprite_data: SpriteData) -> None:
    """スプライトをpresigned URLにアップロードする。"""
    upload_urls = api.styledmap.get_sprite_upload_urls(
        styled_map_id,
        len(sprite_data.json_bytes),
        len(sprite_data.png_bytes),
    )
    server_url = api.config.get_api_config().SERVER_URL
    # presigned の fields に S3 キー("key")を載せて送る（filename がキー）。
    upload_bytes_to_presigned_post(
        url=f"{server_url}{upload_urls.json.url}",
        fields={**upload_urls.json.fields, "key": upload_urls.json.filename},
        data=sprite_data.json_bytes,
    )
    upload_bytes_to_presigned_post(
        url=f"{server_url}{upload_urls.png.url}",
        fields={**upload_urls.png.fields, "key": upload_urls.png.filename},
        data=sprite_data.png_bytes,
    )
