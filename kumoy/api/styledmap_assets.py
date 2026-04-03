"""StyledMapのアセット（スプライト・ZIP）に関するAPIクライアント"""

from dataclasses import dataclass

from .client import ApiClient


@dataclass
class PresignedUrl:
    url: str
    filename: str
    fields: dict[str, str]


@dataclass
class AssetsUploadUrls:
    zip: PresignedUrl
    json: PresignedUrl
    png: PresignedUrl


def get_assets_upload_urls(
    styled_map_id: str,
    zip_file_size: int,
    json_file_size: int,
    png_file_size: int,
) -> AssetsUploadUrls:
    """アセットアップロード用のpresigned URLを取得する（ZIP + スプライト）。

    Args:
        styled_map_id: StyledMap ID
        zip_file_size: ZIPファイルサイズ
        json_file_size: sprite.jsonのファイルサイズ
        png_file_size: sprite.pngのファイルサイズ

    Returns:
        AssetsUploadUrls
    """
    response = ApiClient.post(
        f"/styled-map/{styled_map_id}/assets-upload",
        {
            "zipFileSize": zip_file_size,
            "jsonFileSize": json_file_size,
            "pngFileSize": png_file_size,
        },
    )
    return AssetsUploadUrls(
        zip=PresignedUrl(
            url=response["zip"]["url"],
            filename=response["zip"]["filename"],
            fields=response["zip"]["fields"],
        ),
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


def get_asset_zip_download_url(styled_map_id: str) -> str:
    """ZIPダウンロード用のpresigned URLを取得する。

    Args:
        styled_map_id: StyledMap ID

    Returns:
        ダウンロード用URL文字列
    """
    response = ApiClient.get(f"/styled-map/{styled_map_id}/asset-zip")
    return response["url"]
