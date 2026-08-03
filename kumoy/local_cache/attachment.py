"""Local cache for attachments.

Attachments are immutable (replacement is delete + create on the server), so no
diff sync is needed — download if missing, otherwise use what is there.
"""

import os
import re
from typing import Optional, Tuple

from qgis.core import QgsApplication

from .. import api, download

# Cache paths are built from these, so reject anything unexpected (path traversal).
_VALUE_PATTERN = re.compile(
    r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
    r"\.([A-Za-z0-9]+)$"
)
_UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class InvalidAttachmentValue(Exception):
    pass


def parse_value(value: str) -> Optional[Tuple[str, str]]:
    """Split `{attachmentId}.{ext}`. None if the shape does not match."""
    if not isinstance(value, str):
        return None
    match = _VALUE_PATTERN.match(value)
    if match is None:
        return None
    return match.group(1).lower(), match.group(2).lower()


def _get_cache_dir(vector_id: str) -> str:
    if not _UUID_PATTERN.match(vector_id):
        raise InvalidAttachmentValue(f"Invalid vector id: {vector_id}")
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


def get_cache_path(vector_id: str, value: str) -> str:
    # Keep the extension so QGIS can tell the image format
    parsed = parse_value(value)
    if parsed is None:
        raise InvalidAttachmentValue(f"Invalid attachment value: {value}")
    attachment_id, ext = parsed
    return os.path.join(_get_cache_dir(vector_id), f"{attachment_id}.{ext}")


def is_cached(vector_id: str, value: str) -> bool:
    try:
        return os.path.exists(get_cache_path(vector_id, value))
    except InvalidAttachmentValue:
        return False


def sync_local_cache(
    vector_id: str,
    value: str,
    progress_callback: Optional[download.ProgressCallback] = None,
    is_canceled: Optional[download.IsCanceledCallback] = None,
) -> str:
    """Download the attachment if missing and return its cache path.

    Must stay cheap when already cached: this runs every time a form is shown.
    """
    cache_path = get_cache_path(vector_id, value)
    if os.path.exists(cache_path):
        return cache_path

    attachment_id, _ = parse_value(value)
    url = api.attachment.get_download_url(vector_id, attachment_id)

    # Write to .part first so a canceled download never leaves a broken image
    part_path = f"{cache_path}.part"
    download.download_to_file(url, part_path, progress_callback, is_canceled)
    os.replace(part_path, cache_path)
    return cache_path


def store(vector_id: str, value: str, src_path: str) -> str:
    """Take a local file into the cache, skipping the download after an upload.

    Copies rather than moves: src_path is the file the user picked.
    """
    cache_path = get_cache_path(vector_id, value)
    part_path = f"{cache_path}.part"
    with open(src_path, "rb") as src, open(part_path, "wb") as dst:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            dst.write(chunk)
    os.replace(part_path, cache_path)
    return cache_path


def clear(vector_id: str) -> bool:
    try:
        cache_dir = _get_cache_dir(vector_id)
    except InvalidAttachmentValue:
        return False

    success = True
    for filename in os.listdir(cache_dir):
        try:
            os.unlink(os.path.join(cache_dir, filename))
        except OSError:
            success = False
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
        for filename in os.listdir(path):
            try:
                os.unlink(os.path.join(path, filename))
            except OSError:
                success = False
        try:
            os.rmdir(path)
        except OSError:
            pass
    return success
