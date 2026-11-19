"""Upload a generated sprite (network: kept out of the package's pure core)."""

from .. import api
from ..upload.presigned import upload_bytes_to_presigned_post
from . import SpriteData


def upload_sprites(styled_map_id: str, sprite_data: SpriteData) -> None:
    """Upload sprite.json / sprite.png to the map's presigned POSTs."""
    upload_urls = api.styledmap.get_sprite_upload_urls(
        styled_map_id,
        len(sprite_data.json_bytes),
        len(sprite_data.png_bytes),
    )
    server_url = api.client.server_url()
    # The S3 object key travels in the "key" field (the filename is the key)
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
