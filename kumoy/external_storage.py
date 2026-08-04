"""QgsExternalStorage for Kumoy attachments.

Lets the standard Attachment (External Resource) widget work unchanged: doStore
stages the picked file and its url() becomes the attribute value, doFetch
resolves that value to a local file for the image preview. S3 is never exposed
to QGIS directly.

doStore decides the attachment id, so the value the widget writes is already the
final one. The upload cannot change it, which is why no placeholder value is
needed for a picked-but-not-uploaded file.

Nothing is uploaded here. The widget stores on pick, but a picked file only
becomes an attachment when the layer edits are committed, so the provider does
the upload — that way a rolled-back edit never leaves a file on the server.
"""

import re
import uuid
from typing import Optional, Tuple

from qgis.core import (
    Qgis,
    QgsExternalStorage,
    QgsExternalStorageFetchedContent,
    QgsExternalStorageStoredContent,
)

from . import attachment as attachment_domain
from . import local_cache

STORAGE_TYPE = "kumoy"

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
# The trailing segment is a kumoy_id that in-development projects may still carry
# in their saved widget config; staging never needed it, so it is ignored.
_STORAGE_URL_PATTERN = re.compile(rf"^kumoy://({_UUID})/({_UUID})(?:/\d+)?$")


def build_storage_url_expression(vector_id: str, vector_column_id: str) -> str:
    """Expression for the widget's StorageUrl.

    A constant: staging needs no per-feature value, so this resolves even for a
    feature that has not been saved yet.
    """
    return f"'kumoy://{vector_id}/{vector_column_id}'"


def parse_storage_url(url: str) -> Optional[Tuple[str, str]]:
    match = _STORAGE_URL_PATTERN.match(url or "")
    if match is None:
        return None
    return match.group(1), match.group(2)


def parse_fetch_url(url: str) -> Optional[Tuple[str, str]]:
    """Split `{vectorId}/{value}`.

    The attribute value carries no vector_id, so the widget is configured with
    DefaultRoot = vector_id and RelativeStorage = RelativeDefaultPath.
    """
    parts = (url or "").split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


class _StoredContent(QgsExternalStorageStoredContent):
    def __init__(self, file_path: str, storage_url: str):
        super().__init__()
        self._file_path = file_path
        self._storage_url = storage_url
        self._value = ""
        self._canceled = False

    def store(self) -> None:
        target = parse_storage_url(self._storage_url)
        if target is None:
            self._fail(f"Invalid attachment storage url: {self._storage_url}")
            return

        vector_id, _vector_column_id = target
        try:
            # Reject the file now rather than at commit time, when the user has
            # moved on and the message is harder to tie back to the file
            attachment_domain.validate(self._file_path)
            attachment_id = str(uuid.uuid4())
            local_cache.attachment.stage(vector_id, attachment_id, self._file_path)
            self._value = attachment_id
        except attachment_domain.UnsupportedAttachmentError as e:
            self._fail(f"Unsupported file type: .{e}")
            return
        except attachment_domain.AttachmentTooLargeError:
            self._fail(
                "The file exceeds the maximum attachment size "
                f"({attachment_domain.MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB)"
            )
            return
        except Exception as e:
            self._fail(str(e))
            return

        self.progressChanged.emit(100)
        self.setStatus(Qgis.ContentStatus.Finished)
        self.stored.emit()

    def _fail(self, message: str) -> None:
        self.reportError(message)
        self.setStatus(Qgis.ContentStatus.Failed)
        self.errorOccurred.emit(self.errorString())

    def cancel(self) -> None:
        self._canceled = True
        self.setStatus(Qgis.ContentStatus.Canceled)
        self.canceled.emit()

    def url(self) -> str:
        return self._value


class _FetchedContent(QgsExternalStorageFetchedContent):
    def __init__(self, url: str):
        super().__init__()
        self._url = url
        self._path = ""
        self._canceled = False

    def fetch(self) -> None:
        parsed = parse_fetch_url(self._url)
        if parsed is None:
            self._fail(f"Invalid attachment reference: {self._url}")
            return
        vector_id, attachment_id = parsed

        # Not uploaded yet, so the staged copy is all there is
        if local_cache.attachment.is_staged(vector_id, attachment_id):
            self._path = local_cache.attachment.get_staged_path(
                vector_id, attachment_id
            )
            self.setStatus(Qgis.ContentStatus.Finished)
            self.fetched.emit()
            return

        # Stay off the network when cached: this runs on every form display
        if local_cache.attachment.is_cached(vector_id, attachment_id):
            self._path = local_cache.attachment.get_cache_path(vector_id, attachment_id)
            self.setStatus(Qgis.ContentStatus.Finished)
            self.fetched.emit()
            return

        self.setStatus(Qgis.ContentStatus.Running)
        try:
            self._path = local_cache.attachment.sync_local_cache(
                vector_id,
                attachment_id,
                progress_callback=lambda percent: self.progressChanged.emit(percent),
                is_canceled=lambda: self._canceled,
            )
        except Exception as e:
            self._fail(str(e))
            return

        self.setStatus(Qgis.ContentStatus.Finished)
        self.fetched.emit()

    def _fail(self, message: str) -> None:
        self.reportError(message)
        self.setStatus(Qgis.ContentStatus.Failed)
        self.errorOccurred.emit(self.errorString())

    def cancel(self) -> None:
        self._canceled = True
        self.setStatus(Qgis.ContentStatus.Canceled)
        self.canceled.emit()

    def filePath(self) -> str:
        return self._path


class KumoyExternalStorage(QgsExternalStorage):
    def type(self) -> str:
        return STORAGE_TYPE

    def displayName(self) -> str:
        return "Kumoy"

    def doStore(
        self, filePath: str, url: str, authCfg: str = ""
    ) -> QgsExternalStorageStoredContent:
        return _StoredContent(filePath, url)

    def doFetch(self, url: str, authCfg: str = "") -> QgsExternalStorageFetchedContent:
        return _FetchedContent(url)


# Held so Python does not GC the instance the C++ registry now points at
_storage: Optional[KumoyExternalStorage] = None


def register() -> None:
    from qgis.core import QgsApplication

    global _storage
    registry = QgsApplication.externalStorageRegistry()
    if registry.externalStorageFromType(STORAGE_TYPE) is not None:
        return
    _storage = KumoyExternalStorage()
    registry.registerExternalStorage(_storage)


def unregister() -> None:
    from qgis.core import QgsApplication

    global _storage
    if _storage is None:
        return
    QgsApplication.externalStorageRegistry().unregisterExternalStorage(_storage)
    _storage = None
