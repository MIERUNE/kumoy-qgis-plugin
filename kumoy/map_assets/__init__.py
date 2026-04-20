import hashlib
from typing import Optional

from qgis.core import QgsProject

from .. import api
from .sprite_generator import generate_sprites
from .symbol_collector import collect_sprites
from .uploader import upload_to_presigned_url


def generate_and_upload_sprites(
    styled_map_id: str,
    project: QgsProject,
    current_assets_hash: Optional[str] = None,
) -> Optional[str]:
    """スプライトを生成し、変更があればアップロードする。

    Args:
        styled_map_id: StyledMap ID
        project: QGISプロジェクト
        current_assets_hash: 現在のassetsHash（変更チェック用）

    Returns:
        新しいassetsHash。スプライトがない場合はNone（サーバー側でnullに設定）。
        変更がない場合はcurrent_assets_hashをそのまま返す。
    """
    sprites = collect_sprites(project)
    if not sprites:
        return None

    json_bytes, png_bytes = generate_sprites(sprites)

    # ハッシュ計算
    assets_hash = hashlib.sha256(json_bytes + png_bytes).hexdigest()
    print(assets_hash)
    # 変更なしならアップロードをスキップ
    if current_assets_hash == assets_hash:
        return assets_hash

    # アップロードURL取得
    upload_urls = api.styledmap.get_sprite_upload_urls(
        styled_map_id,
        len(json_bytes),
        len(png_bytes),
    )

    server_url = api.config.get_api_config().SERVER_URL

    # アップロード
    upload_to_presigned_url(
        url=f"{server_url}{upload_urls.json.url}",
        fields=upload_urls.json.fields,
        filename=upload_urls.json.filename,
        file_data=json_bytes,
        content_type="application/json",
    )
    upload_to_presigned_url(
        url=f"{server_url}{upload_urls.png.url}",
        fields=upload_urls.png.fields,
        filename=upload_urls.png.filename,
        file_data=png_bytes,
        content_type="image/png",
    )

    return assets_hash
