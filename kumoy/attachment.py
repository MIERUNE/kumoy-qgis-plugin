"""Attachment upload. Image validation and thumbnailing happen server-side."""

import os
from typing import Optional

from . import api, local_cache
from .upload import presigned

# Client-side pre-checks only; the server re-validates from the actual bytes
EXT_TO_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


class UnsupportedAttachmentError(Exception):
    pass


class AttachmentTooLargeError(Exception):
    pass


# Staged files are named after their attachment id and carry no extension, so the
# content type has to come from the bytes at upload time
_MAGIC_TO_MIME = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)


def validate(file_path: str) -> str:
    """Pre-check a picked file and return its content type.

    Called when the file is picked, not only on upload, so the user hears about
    a rejected file right away instead of at commit time.
    """
    ext = os.path.splitext(file_path)[1].lstrip(".").lower()
    if ext not in EXT_TO_MIME:
        raise UnsupportedAttachmentError(ext or "(no extension)")

    check_size(file_path)

    return EXT_TO_MIME[ext]


def check_size(file_path: str) -> None:
    size = os.path.getsize(file_path)
    if size <= 0 or size > MAX_ATTACHMENT_BYTES:
        raise AttachmentTooLargeError(str(size))


def sniff_content_type(file_path: str) -> str:
    """Content type from the leading bytes.

    Advisory only: the server derives the real format from the bytes too and
    ignores what is declared here. It exists because the name of a staged file
    says nothing about its type.
    """
    with open(file_path, "rb") as f:
        head = f.read(12)

    for magic, mime in _MAGIC_TO_MIME:
        if head.startswith(magic):
            return mime
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"

    raise UnsupportedAttachmentError("unrecognized image data")


def upload(
    vector_id: str,
    vector_column_id: str,
    file_path: str,
    attachment_id: Optional[str] = None,
    progress_callback: Optional[presigned.ProgressCallback] = None,
    is_canceled: Optional[presigned.IsCanceledCallback] = None,
) -> str:
    """Upload an attachment and return the attachment id to store in the column.

    The caller must write that id to the attribute; until then the feature has
    no attachment.
    """
    check_size(file_path)
    content_type = sniff_content_type(file_path)

    upload_info = api.attachment.create_attachment(
        vector_id=vector_id,
        vector_column_id=vector_column_id,
        file_path=file_path,
        content_type=content_type,
        attachment_id=attachment_id,
        progress_callback=progress_callback,
        is_canceled=is_canceled,
    )

    try:
        local_cache.attachment.store(vector_id, upload_info.attachment_id, file_path)
    except Exception:
        # A failed cache warm-up is recovered by the next fetch
        pass

    return upload_info.attachment_id


def upload_staged(
    vector_id: str,
    vector_column_id: str,
    attachment_id: str,
    progress_callback: Optional[presigned.ProgressCallback] = None,
    is_canceled: Optional[presigned.IsCanceledCallback] = None,
) -> None:
    """Upload a file staged by the widget, keeping the id already in the column.

    The staged copy moves into the cache proper, so the preview keeps working
    without downloading what this client just sent.
    """
    upload(
        vector_id=vector_id,
        vector_column_id=vector_column_id,
        file_path=local_cache.attachment.get_staged_path(vector_id, attachment_id),
        attachment_id=attachment_id,
        progress_callback=progress_callback,
        is_canceled=is_canceled,
    )
    local_cache.attachment.promote_staged(vector_id, attachment_id)
