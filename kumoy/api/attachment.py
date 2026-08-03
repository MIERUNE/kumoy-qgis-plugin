from dataclasses import dataclass
from typing import Dict

from .client import ApiClient


@dataclass
class AttachmentUpload:
    attachment_id: str
    # Value to store in the attachment column: `{attachmentId}.{ext}`
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
    """Register an Attachment and get presigned PUT URLs for it."""
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
    """Issue a presigned GET URL. Short-lived, so fetch it right before use."""
    response = ApiClient.get(
        f"/_qgis/vector/{vector_id}/attachment/{attachment_id}/download"
    )
    return response.get("url", "")
