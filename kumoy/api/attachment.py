import json
from dataclasses import dataclass
from typing import Optional

from ..get_token import get_token
from ..upload import presigned
from . import config as api_config
from . import error as api_error
from .client import ApiClient


@dataclass
class AttachmentUpload:
    # Value to store in the attachment column
    attachment_id: str


def create_attachment(
    vector_id: str,
    vector_column_id: str,
    file_path: str,
    content_type: str,
    attachment_id: Optional[str] = None,
    progress_callback: Optional[presigned.ProgressCallback] = None,
    is_canceled: Optional[presigned.IsCanceledCallback] = None,
) -> AttachmentUpload:
    """Upload an attachment file as multipart/form-data.

    The server validates the image from the actual bytes, derives the
    extension, and generates the thumbnail. No feature is named here: the file
    is linked to one only when the returned id is written to the column, so a
    not-yet-committed feature can have an attachment too.

    ``attachment_id`` lets the caller keep the id it already wrote to the
    column; the server rejects one that is in use.
    """
    token = get_token()
    if not token:
        raise api_error.UnauthorizedError("Unauthorized", "No session token")

    server_url = api_config.get_api_config().SERVER_URL
    url = f"{server_url}/api/_qgis/vector/{vector_id}/attachment"

    status_code, body = presigned.post_multipart_form(
        url,
        fields=(
            {"vectorColumnId": vector_column_id, "attachmentId": attachment_id}
            if attachment_id
            else {"vectorColumnId": vector_column_id}
        ),
        file_path=file_path,
        content_type=content_type,
        headers={"Authorization": f"Bearer {token}"},
        progress_callback=progress_callback,
        is_canceled=is_canceled,
    )

    try:
        content = json.loads(body.decode("utf-8")) if body else {}
    except ValueError:
        content = {}
    if not isinstance(content, dict):
        content = {}

    if status_code in (401, 403):
        detail = content.get("error", "") or content.get("message", "")
        raise api_error.UnauthorizedError("Unauthorized", detail)
    if status_code != 200:
        api_error.raise_error(
            content or {"message": f"HTTP {status_code}", "error": ""}
        )

    return AttachmentUpload(attachment_id=content.get("attachmentId", ""))


def get_download_url(vector_id: str, attachment_id: str) -> str:
    """Issue a presigned GET URL. Short-lived, so fetch it right before use."""
    response = ApiClient.get(
        f"/_qgis/vector/{vector_id}/attachment/{attachment_id}/download"
    )
    return response.get("url", "")
