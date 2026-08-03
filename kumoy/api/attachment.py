"""Attachment API（Vector 地物への添付ファイル）。

添付の実体は S3 にあり、プラグインは常にバックエンドの認可を経由して
短命な presigned URL を受け取る。S3 の URL を保存・使い回すことはしない。
"""

from dataclasses import dataclass
from typing import Dict

from .client import ApiClient


@dataclass
class AttachmentUpload:
    """``POST /_qgis/vector/{id}/attachment`` のレスポンス。

    ``value`` は属性カラムに格納すべき値（``{attachmentId}.{ext}``）。
    PUT 完了後にこの値を属性へ書き込んで初めて「地物に付いた」状態になる。
    """

    attachment_id: str
    value: str
    upload_url: str
    thumbnail_upload_url: str


def create_attachment(
    vector_id: str,
    kumoy_id: int,
    vector_column_id: str,
    ext: str,
    bytes: int,
    thumbnail_bytes: int,
) -> AttachmentUpload:
    """Attachment を登録し、原本とサムネイルの presigned PUT URL を取得する。

    Args:
        vector_id: 対象 Vector の ID
        kumoy_id: 添付先の地物の kumoy_id（添付は既存の地物に対してのみ行える）
        vector_column_id: 添付先の attachment 型カラムの ID
        ext: 原本の拡張子（jpg / png / webp）
        bytes: 原本のバイト数
        thumbnail_bytes: サムネイル（WebP）のバイト数

    Raises:
        QuotaExceededError: ストレージ上限超過時（429）。
        ValidateError: 拡張子・サイズ・カラム種別が不正な場合（422）。
    """
    payload: Dict[str, object] = {
        "kumoyId": kumoy_id,
        "vectorColumnId": vector_column_id,
        "ext": ext,
        "bytes": bytes,
        "thumbnailBytes": thumbnail_bytes,
    }
    response = ApiClient.post(f"/_qgis/vector/{vector_id}/attachment", payload)

    return AttachmentUpload(
        attachment_id=response.get("attachmentId", ""),
        value=response.get("value", ""),
        upload_url=response.get("uploadUrl", ""),
        thumbnail_upload_url=response.get("thumbnailUploadUrl", ""),
    )


def get_download_url(vector_id: str, attachment_id: str) -> str:
    """原本を S3 から取得するための presigned GET URL を発行する。

    短時間で失効するため、ダウンロード直前に都度取得する（保存・使い回ししない）。
    """
    response = ApiClient.get(
        f"/_qgis/vector/{vector_id}/attachment/{attachment_id}/download"
    )
    return response.get("url", "")
