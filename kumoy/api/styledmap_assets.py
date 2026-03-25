"""StyledMapのアセット（スプライト・ZIP）に関するAPIクライアント"""

from dataclasses import dataclass

from .client import ApiClient


@dataclass
class PresignedUrl:
    url: str
    filename: str
    fields: dict[str, str]


@dataclass
class SpriteUploadUrls:
    json: PresignedUrl
    png: PresignedUrl


def get_sprite_upload_urls(
    styled_map_id: str, json_file_size: int, png_file_size: int
) -> SpriteUploadUrls:
    """スプライトアップロード用のpresigned URLを取得する。

    Args:
        styled_map_id: StyledMap ID
        json_file_size: sprite.jsonのファイルサイズ
        png_file_size: sprite.pngのファイルサイズ

    Returns:
        SpriteUploadUrls
    """
    response = ApiClient.post(
        f"/styled-map/{styled_map_id}/sprite-upload",
        {
            "jsonFileSize": json_file_size,
            "pngFileSize": png_file_size,
        },
    )
    return SpriteUploadUrls(
        json=PresignedUrl(
            url=response["json"]["url"],
            filename=response["json"]["filename"],
            fields=response["json"]["fields"],
        ),
        png=PresignedUrl(
            url=response["png"]["url"],
            filename=response["png"]["filename"],
            fields=response["png"]["fields"],
        ),
    )


def get_asset_zip_upload_url(styled_map_id: str, file_size: int) -> PresignedUrl:
    """ZIPアップロード用のpresigned URLを取得する。

    Args:
        styled_map_id: StyledMap ID
        file_size: ZIPファイルサイズ

    Returns:
        PresignedUrl
    """
    response = ApiClient.post(
        f"/styled-map/{styled_map_id}/asset-zip-upload",
        {"fileSize": file_size},
    )
    return PresignedUrl(
        url=response["url"],
        filename=response["filename"],
        fields=response["fields"],
    )


def get_asset_zip_download_url(styled_map_id: str) -> str:
    """ZIPダウンロード用のpresigned URLを取得する。

    Args:
        styled_map_id: StyledMap ID

    Returns:
        ダウンロード用URL文字列
    """
    response = ApiClient.get(f"/styled-map/{styled_map_id}/asset-zip")
    return response["url"]
