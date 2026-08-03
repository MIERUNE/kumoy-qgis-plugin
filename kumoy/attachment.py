"""Attachment upload. Thumbnails are generated client-side (no server-side imaging)."""

import os
import tempfile
from typing import Optional

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QBuffer, QByteArray
from qgis.PyQt.QtGui import QImage

from ..pyqt_version import (
    Q_IODEVICE_OPEN_MODE,
    QT_ASPECT_RATIO_MODE,
    QT_TRANSFORMATION_MODE,
)
from . import api, local_cache
from .upload import presigned

# Must match the server allowlist
EXT_TO_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}
_EXT_ALIAS = {"jpeg": "jpg"}

THUMBNAIL_MIME = "image/webp"
_THUMBNAIL_MAX_EDGE = 512
_THUMBNAIL_QUALITY = 75

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


class UnsupportedAttachmentError(Exception):
    pass


class AttachmentTooLargeError(Exception):
    pass


def normalized_ext(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lstrip(".").lower()
    if ext not in EXT_TO_MIME:
        raise UnsupportedAttachmentError(ext)
    return _EXT_ALIAS.get(ext, ext)


def create_thumbnail_bytes(file_path: str) -> bytes:
    """Re-encode to WebP, longest edge 512px. This also strips EXIF."""
    image = QImage(file_path)
    if image.isNull():
        raise Exception(f"Cannot read image: {file_path}")

    if max(image.width(), image.height()) > _THUMBNAIL_MAX_EDGE:
        image = image.scaled(
            _THUMBNAIL_MAX_EDGE,
            _THUMBNAIL_MAX_EDGE,
            QT_ASPECT_RATIO_MODE.KeepAspectRatio,
            QT_TRANSFORMATION_MODE.SmoothTransformation,
        )

    byte_array = QByteArray()
    buffer = QBuffer(byte_array)
    buffer.open(Q_IODEVICE_OPEN_MODE.WriteOnly)
    if not image.save(buffer, "WEBP", _THUMBNAIL_QUALITY):
        raise Exception("Failed to encode thumbnail as WebP")
    buffer.close()

    return bytes(byte_array)


def upload(
    vector_id: str,
    kumoy_id: int,
    vector_column_id: str,
    file_path: str,
    progress_callback: Optional[presigned.ProgressCallback] = None,
    is_canceled: Optional[presigned.IsCanceledCallback] = None,
) -> str:
    """Upload an attachment and return the value to store in the column.

    The caller must write that value to the attribute; until then the feature has
    no attachment (an interrupted upload only leaves an unreferenced row).
    """
    ext = normalized_ext(file_path)
    size = os.path.getsize(file_path)
    if size <= 0 or size > MAX_ATTACHMENT_BYTES:
        raise AttachmentTooLargeError(str(size))

    thumbnail = create_thumbnail_bytes(file_path)

    upload_info = api.attachment.create_attachment(
        vector_id=vector_id,
        kumoy_id=kumoy_id,
        vector_column_id=vector_column_id,
        ext=ext,
        bytes=size,
        thumbnail_bytes=len(thumbnail),
    )

    presigned.upload_file_to_presigned_put(
        upload_info.upload_url,
        file_path,
        EXT_TO_MIME[ext],
        progress_callback,
        is_canceled,
    )
    _put_bytes(upload_info.thumbnail_upload_url, thumbnail)

    try:
        local_cache.attachment.store(vector_id, upload_info.value, file_path)
    except Exception:
        # A failed cache warm-up is recovered by the next fetch
        pass

    return upload_info.value


def _put_bytes(url: str, data: bytes) -> None:
    """PUT an in-memory blob via a temp file.

    upload_file_to_presigned_put streams from a QIODevice; going through a temp
    file keeps thumbnails on the same upload path as originals.
    """
    fd, temp_path = tempfile.mkstemp(
        suffix=".webp", dir=QgsApplication.qgisSettingsDirPath()
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        presigned.upload_file_to_presigned_put(url, temp_path, THUMBNAIL_MIME)
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
