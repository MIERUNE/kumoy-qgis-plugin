"""Local cache for attachments.

Attachments are immutable (replacement is delete + create on the server), so no
diff sync is needed — download if missing, otherwise use what is there.
"""

import os
import re
from typing import Optional

from qgis.core import QgsApplication

from .. import api, download

# Cache paths are built from these, so reject anything unexpected (path traversal).
_UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
# Files picked but not uploaded yet, keyed by the attachment id the widget chose.
# They live in a subdirectory so a staged file is never mistaken for a cached one.
_STAGED_DIR = "staged"


class InvalidAttachmentId(Exception):
    pass


def parse_attachment_id(attachment_id: str) -> Optional[str]:
    """Normalize the column value. None if it is not an attachment id."""
    if not isinstance(attachment_id, str):
        return None
    if _UUID_PATTERN.match(attachment_id) is None:
        return None
    return attachment_id.lower()


def _get_cache_dir(vector_id: str) -> str:
    if not _UUID_PATTERN.match(vector_id):
        raise InvalidAttachmentId(f"Invalid vector id: {vector_id}")
    setting_dir = QgsApplication.qgisSettingsDirPath()
    cache_dir = os.path.join(
        setting_dir, "kumoygis", "local_cache", "attachments", vector_id
    )
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def get_root_dir() -> str:
    setting_dir = QgsApplication.qgisSettingsDirPath()
    root = os.path.join(setting_dir, "kumoygis", "local_cache", "attachments")
    os.makedirs(root, exist_ok=True)
    return root


def get_cache_path(vector_id: str, attachment_id: str) -> str:
    # No extension: the server no longer reports one, and Qt detects the image
    # format from the file content anyway
    parsed = parse_attachment_id(attachment_id)
    if parsed is None:
        raise InvalidAttachmentId(f"Invalid attachment id: {attachment_id}")
    return os.path.join(_get_cache_dir(vector_id), parsed)


def is_cached(vector_id: str, attachment_id: str) -> bool:
    try:
        return os.path.exists(get_cache_path(vector_id, attachment_id))
    except InvalidAttachmentId:
        return False


def sync_local_cache(
    vector_id: str,
    attachment_id: str,
    progress_callback: Optional[download.ProgressCallback] = None,
    is_canceled: Optional[download.IsCanceledCallback] = None,
) -> str:
    """Download the attachment if missing and return its cache path.

    Must stay cheap when already cached: this runs every time a form is shown.
    """
    cache_path = get_cache_path(vector_id, attachment_id)
    if os.path.exists(cache_path):
        return cache_path

    # Not on the server yet, so there is nothing to download
    if is_staged(vector_id, attachment_id):
        return get_staged_path(vector_id, attachment_id)

    url = api.attachment.get_download_url(vector_id, parse_attachment_id(attachment_id))

    # Write to .part first so a canceled download never leaves a broken image
    part_path = f"{cache_path}.part"
    download.download_to_file(url, part_path, progress_callback, is_canceled)
    os.replace(part_path, cache_path)
    return cache_path


def store(vector_id: str, attachment_id: str, src_path: str) -> str:
    """Take a local file into the cache, skipping the download after an upload.

    Copies rather than moves: src_path is the file the user picked.
    """
    cache_path = get_cache_path(vector_id, attachment_id)
    _copy_into_cache(src_path, cache_path)
    return cache_path


def get_staged_path(vector_id: str, attachment_id: str) -> str:
    parsed = parse_attachment_id(attachment_id)
    if parsed is None:
        raise InvalidAttachmentId(f"Invalid attachment id: {attachment_id}")
    staged_dir = os.path.join(_get_cache_dir(vector_id), _STAGED_DIR)
    os.makedirs(staged_dir, exist_ok=True)
    return os.path.join(staged_dir, parsed)


def is_staged(vector_id: str, attachment_id) -> bool:
    """True for an attachment whose file is still only local."""
    try:
        return os.path.exists(get_staged_path(vector_id, attachment_id))
    except InvalidAttachmentId:
        return False


def stage(vector_id: str, attachment_id: str, src_path: str) -> str:
    """Copy a picked file into the staging area under its attachment id.

    The upload happens on commit, so the file has to survive until then even if
    the user moves or deletes the one they picked.
    """
    staged_path = get_staged_path(vector_id, attachment_id)
    _copy_into_cache(src_path, staged_path)
    return staged_path


def promote_staged(vector_id: str, attachment_id: str) -> None:
    """Move an uploaded file out of staging, so the preview needs no download."""
    try:
        os.replace(
            get_staged_path(vector_id, attachment_id),
            get_cache_path(vector_id, attachment_id),
        )
    except (OSError, InvalidAttachmentId):
        discard_staged(vector_id, attachment_id)


def discard_staged(vector_id: str, attachment_id) -> None:
    """Drop a staged file once the edit that owned it is rolled back."""
    try:
        os.unlink(get_staged_path(vector_id, attachment_id))
    except (OSError, InvalidAttachmentId):
        pass


def _copy_into_cache(src_path: str, cache_path: str) -> None:
    # Write to .part first so a failure never leaves a truncated image behind
    part_path = f"{cache_path}.part"
    with open(src_path, "rb") as src, open(part_path, "wb") as dst:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            dst.write(chunk)
    os.replace(part_path, cache_path)


def clear(vector_id: str) -> bool:
    try:
        cache_dir = _get_cache_dir(vector_id)
    except InvalidAttachmentId:
        return False

    success = _clear_dir(cache_dir)
    if success:
        try:
            os.rmdir(cache_dir)
        except OSError:
            pass
    return success


def clear_all() -> bool:
    root = get_root_dir()
    success = True
    for vector_dir in os.listdir(root):
        path = os.path.join(root, vector_dir)
        if not os.path.isdir(path):
            continue
        if not _clear_dir(path):
            success = False
        try:
            os.rmdir(path)
        except OSError:
            pass
    return success


def _clear_dir(directory: str) -> bool:
    """Remove the cached files and the staging subdirectory under it."""
    success = True
    for filename in os.listdir(directory):
        path = os.path.join(directory, filename)
        if os.path.isdir(path):
            if not _clear_dir(path):
                success = False
            try:
                os.rmdir(path)
            except OSError:
                success = False
            continue
        try:
            os.unlink(path)
        except OSError:
            success = False
    return success
