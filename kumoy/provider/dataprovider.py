"""Kumoy vector data provider and the background sync of its local cache.

Lifecycle:
- With a local cache the provider opens it immediately (no network) and
  starts a background sync.
- Without one, the constructor makes one blocking metadata request (QGIS
  needs the fields synchronously) and downloads the features in the
  background; the layer is empty and read-only until that finishes.
- When a sync of the vector finishes, every provider of it reopens the cache
  and refreshes its layers (fields, attribute tables, canvas).

Edits go to the server first, then into the local cache, so the layer shows
them right after the commit; a background diff sync then picks up changes
made by others.
"""

import threading
import weakref
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsDataProvider,
    QgsErrorMessage,
    QgsFeatureRequest,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsMessageLog,
    QgsProject,
    QgsProviderRegistry,
    QgsRectangle,
    QgsVectorDataProvider,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QMetaType, QObject, QTimer, QVariant, pyqtSignal

from ... import i18n
from .. import api, constants, local_cache, session
from ..api.error import (
    AppError,
    ForbiddenError,
    QuotaExceededError,
    format_api_error,
)
from ..api.models import Column, VectorDetail, is_editor
from ..api.qgis_vector import (
    FEATURES_PAGE_SIZE,
    MAX_DIFF_COUNT_EXCEEDED,
    MAX_ITEMS_PER_REQUEST,
    MAX_WKB_BASE64_LENGTH,
)
from ..tasks import Canceled, FunctionTask, run_task
from ..shared import shared
from .feature_source import KumoyFeatureSource

# get-diff compares against kumoy_updatedat, the database's transaction start
# time, read from a replica. Rows written by a transaction that began before
# our timestamp but committed (or replicated) after our query would be missed
# for good, so the timestamp is moved back; re-applying a row is idempotent.
SYNC_MARGIN = timedelta(seconds=60)
# Without a Date header the client clock is all we have; it may be off
SYNC_MARGIN_CLIENT_CLOCK = timedelta(minutes=10)

_WKB_TYPES = {
    "POINT": Qgis.WkbType.Point,
    "LINESTRING": Qgis.WkbType.LineString,
    "POLYGON": Qgis.WkbType.Polygon,
}

_T = QMetaType.Type
_SERVER_TYPES = {
    _T.Int: "integer",
    _T.UInt: "integer",
    _T.LongLong: "integer",
    _T.ULongLong: "integer",
    _T.Double: "float",
    _T.Bool: "boolean",
    _T.QString: "string",
}


# --- URI ---------------------------------------------------------------------


def decode_uri(uri: str) -> Dict[str, str]:
    """`project_id=..;vector_id=..;vector_name=..;vector_type=..;subset=..`

    `subset` is always last and may itself contain semicolons.
    """
    params: Dict[str, str] = {}
    head, sep, subset = uri.partition(";subset=")
    if sep:
        params["subset"] = subset
    for part in head.split(";"):
        key, sep, value = part.partition("=")
        if sep and key:
            params[key] = value
    return params


def encode_uri(parts: Dict[str, str]) -> str:
    segments = [f"{k}={v}" for k, v in parts.items() if k != "subset"]
    uri = ";".join(segments)
    if parts.get("subset"):
        uri += f";subset={parts['subset']}"
    return uri


# --- Sync --------------------------------------------------------------------


class SyncEvents(QObject):
    """Progress of background syncs, for the UI (lives in the main thread).

    sync_failed carries the exception so the UI can pass it to its error
    handler (401 ends the session; a canceled sync carries tasks.Canceled).
    """

    sync_started = pyqtSignal(str)  # vector_id
    sync_finished = pyqtSignal(str)  # vector_id; the cache was updated
    sync_failed = pyqtSignal(str, str, object)  # vector_id, message, exception


sync_events = shared("vector_sync_events", SyncEvents)

_running: Dict[str, FunctionTask] = {}  # main thread only
_rerun: Set[str] = set()
_sync_locks: Dict[str, threading.Lock] = {}
# How often a full download catches up with edits made while it ran before
# it completes anyway (the sync queued by those edits fixes the rest)
_CATCH_UP_ATTEMPTS = 3
_sync_locks_guard = threading.Lock()
# Metadata handed over by create_vector_layer so a first open needs no request
_primed: Dict[str, VectorDetail] = {}
# Live providers: cleanup must not delete a cache file one of them reads
_providers: "weakref.WeakSet[KumoyDataProvider]" = weakref.WeakSet()
_providers_lock = threading.Lock()


def prime_vector(vector: VectorDetail) -> None:
    _primed[vector.id] = vector


def _log(message: str, level=Qgis.Info) -> None:
    QgsMessageLog.logMessage(message, constants.LOG_CATEGORY, level)


def _is_main_thread() -> bool:
    return threading.current_thread() is threading.main_thread()


def _sync_lock(vector_id: str) -> threading.Lock:
    with _sync_locks_guard:
        return _sync_locks.setdefault(vector_id, threading.Lock())


def _paths_in_use() -> Set[str]:
    with _providers_lock:  # added from the main thread, read by syncs
        providers = list(_providers)
    return {p._cache_path for p in providers if p._cache_path and not sip.isdeleted(p)}


def sync_vector(vector_id: str, name: str = "", rerun: bool = True) -> None:
    """Start a background sync of the vector's cache (main thread only).

    While one runs for the vector, `rerun` makes it run once more afterwards:
    after an edit the running one may have fetched too early. Opening more
    layers of the vector passes False and just waits for the running one.
    """
    if not _is_main_thread():
        return  # no event loop to deliver the result; caches are updated later
    if vector_id in _running:
        if rerun:
            _rerun.add(vector_id)
        return
    _rerun.discard(vector_id)

    def finish(task: FunctionTask) -> None:
        if _running.get(vector_id) is task:
            del _running[vector_id]

    def on_success(_result) -> None:
        finish(task)
        sync_events.sync_finished.emit(vector_id)
        if vector_id in _rerun:
            sync_vector(vector_id, name)

    def on_error(e: Exception) -> None:
        finish(task)
        _log(f"Sync of vector {name or vector_id} failed: {e}", Qgis.Warning)
        sync_events.sync_failed.emit(vector_id, format_api_error(e), e)

    def on_terminated() -> None:
        # Canceled tasks call neither callback
        if _running.get(vector_id) is task:
            finish(task)
            sync_events.sync_failed.emit(vector_id, "", Canceled())

    task = run_task(
        i18n.tr("Syncing vector: {}").format(name or vector_id),
        lambda t: sync_now(vector_id, t),
        on_success,
        on_error,
        can_cancel=True,
    )
    task.taskTerminated.connect(on_terminated)
    _running[vector_id] = task
    sync_events.sync_started.emit(vector_id)


def sync_now(vector_id: str, task: Optional[FunctionTask] = None) -> None:
    """Bring the vector's cache up to date. Blocking; any thread."""
    with _sync_lock(vector_id):
        try:
            _sync(vector_id, task)
        finally:
            local_cache.vector.cleanup(vector_id, keep=_paths_in_use())


def _sync(vector_id: str, task: Optional[FunctionTask]) -> None:
    # Data fetched from here on may predate an edit made meanwhile; such
    # writes are skipped (see local_cache.vector.write)
    edits_seen = local_cache.vector.local_edit_count(vector_id)
    # The timestamp is taken before any feature query: rows changed while
    # we download are newer than it and come with the next diff
    vector, server_time = api.qgis_vector.get_vector_and_server_time(vector_id)
    if task is not None:
        task.check_canceled()
    if server_time is None:
        server_time = datetime.now(timezone.utc) - SYNC_MARGIN_CLIENT_CLOCK
    elif server_time.tzinfo is None:
        server_time = server_time.replace(tzinfo=timezone.utc)
    last_updated = (server_time.astimezone(timezone.utc) - SYNC_MARGIN).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    cache = local_cache.vector.open_cache(vector_id)
    if cache is not None and _same_schema(cache.vector, vector):
        try:
            diff = api.qgis_vector.get_diff(vector_id, cache.last_updated)
        except AppError as e:
            if e.error != MAX_DIFF_COUNT_EXCEEDED:
                raise
            _log(f"Vector {vector.name}: too many changes, downloading all")
        else:
            written = local_cache.vector.write(
                cache.path,
                diff.updated_rows,
                diff.deleted_ids,
                vector=vector,
                last_updated=last_updated,
                edits_seen=edits_seen,
            )
            if not written:
                # The diff may predate the edit. Its cache write already shows
                # it, and the sync it queued fetches the rest
                _log(f"Vector {vector.name} was edited during sync; skipped diff")
            return

    # Full download into a new file; the current one stays usable meanwhile
    path = local_cache.vector.create(vector)
    after_id = None
    done = 0
    while True:
        if task is not None:
            task.check_canceled()
        rows = api.qgis_vector.get_features(vector_id, after_id)
        local_cache.vector.write(path, rows)
        if len(rows) < FEATURES_PAGE_SIZE:
            break
        done += len(rows)
        after_id = rows[-1]["kumoy_id"]
        if task is not None:
            task.setProgress(min(99.0, done * 100.0 / max(vector.count, 1)))
    _complete(path, vector_id, vector, last_updated, edits_seen)


def _complete(
    path: str, vector_id: str, vector: VectorDetail, last_updated: str, edits_seen: int
) -> None:
    """Mark a full download complete, so that providers switch to it.

    Pages fetched before an edit lack it, and the edit's own cache write went
    to the previous file: completing as is would hide the edit until the next
    sync. Catch up with a diff first.
    """
    for _ in range(_CATCH_UP_ATTEMPTS):
        if local_cache.vector.write(
            path,
            [],
            vector=vector,
            last_updated=last_updated,
            edits_seen=edits_seen,
        ):
            return
        edits_seen = local_cache.vector.local_edit_count(vector_id)
        try:
            diff = api.qgis_vector.get_diff(vector_id, last_updated)
        except AppError as e:
            if e.error != MAX_DIFF_COUNT_EXCEEDED:
                raise
            break
        local_cache.vector.write(path, diff.updated_rows, diff.deleted_ids)
    # Still being edited: complete anyway; the syncs the edits queued catch up
    local_cache.vector.write(path, [], vector=vector, last_updated=last_updated)


def _same_schema(a: VectorDetail, b: VectorDetail) -> bool:
    return a.type == b.type and [(c.name, c.type) for c in a.columns] == [
        (c.name, c.type) for c in b.columns
    ]


# --- Edit helpers --------------------------------------------------------------


def _json_value(value):
    if isinstance(value, QVariant):
        if value.isNull():
            return None
        value = value.value()
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _describe(e: Exception) -> str:
    """User-readable message for pushError (wording as ui/error_handler)."""
    detail = format_api_error(e)
    if isinstance(e, ForbiddenError):
        return i18n.tr(
            "You do not have permission for this operation. Editing requires the "
            "Editor role in the project's team, and some features require a paid "
            "plan. Details: {}"
        ).format(detail)
    if isinstance(e, QuotaExceededError):
        return i18n.tr(
            "Your organization has reached a limit of its plan. Details: {}"
        ).format(detail)
    return detail


def _qgs_field(column: Column) -> QgsField:
    if column.type == "integer":
        return QgsField(column.name, _T.LongLong)
    if column.type == "float":
        return QgsField(column.name, _T.Double)
    if column.type == "boolean":
        return QgsField(column.name, _T.Bool)
    return QgsField(column.name, _T.QString, len=constants.MAX_CHARACTERS_STRING_FIELD)


class _EditError(Exception):
    """An edit that cannot be sent; the message is already user-readable."""


# --- Provider ----------------------------------------------------------------


class KumoyDataProvider(QgsVectorDataProvider):
    def __init__(
        self,
        uri="",
        providerOptions=QgsDataProvider.ProviderOptions(),
        flags=Qgis.DataProviderReadFlags(),
    ):
        super().__init__(uri, providerOptions, flags)
        parts = decode_uri(uri)
        self._vector_id = parts.get("vector_id", "")
        self._name = parts.get("vector_name", "")
        self._uri_type = parts.get("vector_type", "")
        self._subset = parts.get("subset", "")
        self._crs = QgsCoordinateReferenceSystem("EPSG:4326")
        self._vector: Optional[VectorDetail] = None
        self._columns: List[Column] = []
        # Fields as QGIS asked for them in addAttributes, until the next
        # schema reload: the edit buffer compares them with fields() and
        # aborts the commit on any difference (e.g. Int vs LongLong)
        self._added_fields: Dict[str, QgsField] = {}
        self._fields = QgsFields()
        self._cache_path: Optional[str] = None
        self._cache_provider: Optional[QgsVectorDataProvider] = None
        self._in_edit = False
        self._reload_pending = False
        # Fields were added/deleted here and the cache has not caught up
        self._schema_ahead = False
        self._set_native_types()

        primed = _primed.pop(self._vector_id, None)
        if not self._vector_id:
            self.appendError(QgsErrorMessage("Invalid URI: vector_id is missing"))
            return

        if self._open_cache():
            if session.is_logged_in():
                sync_vector(self._vector_id, self._name, rerun=False)
        else:
            try:
                if _is_main_thread():
                    self._vector = primed or api.vector.get_vector(self._vector_id)
                    self._set_columns(self._vector.columns)
                    sync_vector(self._vector_id, self._name, rerun=False)
                else:
                    # Processing etc.: blocking is fine and the caller needs data
                    sync_now(self._vector_id)
                    self._open_cache()
            except Exception as e:
                message = i18n.tr("Cannot load vector {}: {}").format(
                    self._name or self._vector_id, format_api_error(e)
                )
                _log(message, Qgis.Warning)
                self.appendError(QgsErrorMessage(message, constants.LOG_CATEGORY))
                sync_events.sync_failed.emit(self._vector_id, message, e)
                return

        with _providers_lock:
            _providers.add(self)
        sync_events.sync_finished.connect(self._on_sync_finished)

    # --- Cache --------------------------------------------------------------

    def _open_cache(self, keep_columns: bool = False) -> bool:
        """Switch to the newest complete cache. False when there is none."""
        cache = local_cache.vector.open_cache(self._vector_id)
        if cache is None:
            return False
        provider = QgsProviderRegistry.instance().createProvider(
            "ogr", local_cache.vector.ogr_uri(cache.path)
        )
        if provider is None or not provider.isValid():
            _log(f"Cannot open cache {cache.path}", Qgis.Warning)
            return False
        if self._subset and not provider.setSubsetString(self._subset):
            _log(f"Invalid filter on {self._name}: {self._subset}", Qgis.Warning)
        self._cache_provider = provider
        self._cache_path = cache.path
        self._vector = cache.vector
        if not keep_columns:
            self._added_fields.clear()
            self._set_columns(cache.vector.columns)
        return True

    def _set_columns(self, columns: List[Column]) -> None:
        self._columns = list(columns)
        fields = QgsFields()
        fields.append(QgsField("kumoy_id", _T.LongLong))
        for column in self._columns:
            fields.append(self._added_fields.get(column.name) or _qgs_field(column))
        self._fields = fields

    def _layers(self) -> List[QgsVectorLayer]:
        return [
            layer
            for layer in QgsProject.instance().mapLayers().values()
            if isinstance(layer, QgsVectorLayer) and layer.dataProvider() is self
        ]

    def _on_sync_finished(self, vector_id: str) -> None:
        if vector_id == self._vector_id:
            self._schedule_reload()

    def _schedule_reload(self) -> None:
        # Deferred to the event loop: a sync can finish inside the nested
        # event loop of a network request in the middle of a commit
        self._reload_pending = True
        QTimer.singleShot(0, self._reload_if_pending)

    def _reload_if_pending(self) -> None:
        if sip.isdeleted(self) or not self._reload_pending or self._in_edit:
            return
        self._reload_pending = False
        layers = self._layers()
        # Pending edits refer to fields by index: keep the schema until saved.
        # After addAttributes/deleteAttributes the cache has the old schema
        # until the sync started after the change has finished.
        keep = (self._schema_ahead and self._vector_id in _running) or any(
            layer.isEditable() and layer.isModified() for layer in layers
        )
        old_fields = self._fields
        if not self._open_cache(keep_columns=keep):
            return
        if not keep:
            self._schema_ahead = False
        if self._fields != old_fields:
            for layer in layers:
                layer.updateFields()
        self.clearMinMaxCache()
        # Layer -> attribute tables reload, extent is recalculated
        self.dataChanged.emit()
        for layer in layers:
            layer.triggerRepaint()

    def sync(self) -> None:
        """Start a background sync with the server ("Sync Data")."""
        sync_vector(self._vector_id, self._name)

    # --- QgsDataProvider ----------------------------------------------------

    @classmethod
    def providerKey(cls) -> str:
        return constants.DATA_PROVIDER_KEY

    @classmethod
    def description(cls) -> str:
        return constants.DATA_PROVIDER_DESCRIPTION

    @classmethod
    def createProvider(cls, uri, providerOptions, flags=Qgis.DataProviderReadFlags()):
        return KumoyDataProvider(uri, providerOptions, flags)

    def name(self) -> str:
        return constants.DATA_PROVIDER_KEY

    def isValid(self) -> bool:
        return self._vector is not None

    def crs(self) -> QgsCoordinateReferenceSystem:
        return self._crs

    def wkbType(self):
        type_ = self._vector.type if self._vector else self._uri_type
        return _WKB_TYPES.get(type_, Qgis.WkbType.Unknown)

    def fields(self) -> QgsFields:
        return self._fields

    def featureCount(self) -> int:
        # The features we can return, not the server's count
        return self._cache_provider.featureCount() if self._cache_provider else 0

    def extent(self) -> QgsRectangle:
        if self._cache_provider is not None:
            return self._cache_provider.extent()
        if self._vector is not None and len(self._vector.extent) == 4:
            return QgsRectangle(*self._vector.extent)
        return QgsRectangle()

    def updateExtents(self) -> None:
        if self._cache_provider is not None:
            self._cache_provider.updateExtents()

    def capabilities(self):
        cap = Qgis.VectorProviderCapability
        read = Qgis.VectorProviderCapabilities(cap.SelectAtId)
        # Read-only until the first download finished: edits need the cache
        if self._cache_provider is None or not is_editor(self._vector.role):
            return read
        return (
            read
            | cap.AddFeatures
            | cap.DeleteFeatures
            | cap.ChangeAttributeValues
            | cap.ChangeGeometries
            | cap.ChangeFeatures
            | cap.AddAttributes
            | cap.DeleteAttributes
        )

    def doesStrictFeatureTypeCheck(self) -> bool:
        # Let other geometry types reach addFeatures: they are converted
        # there or rejected with a clear message
        return False

    def featureSource(self):
        if self._cache_provider is None:
            return KumoyFeatureSource(self._fields)
        cache_fields = self._cache_provider.fields()
        if cache_fields.names() == self._fields.names():
            return self._cache_provider.featureSource()
        return KumoyFeatureSource(
            self._fields, self._cache_provider.featureSource(), cache_fields
        )

    def getFeatures(self, request=QgsFeatureRequest()):
        if (
            self._cache_provider is not None
            and self._cache_provider.fields().names() == self._fields.names()
        ):
            # Not featureSource().getFeatures(): ogr iterators do not own
            # their source and it would be freed on return
            return self._cache_provider.getFeatures(request)
        return self.featureSource().getFeatures(request)

    # --- Subset string ------------------------------------------------------

    def supportsSubsetString(self) -> bool:
        return True

    def subsetStringDialect(self) -> str:
        return "GeoPackage query"

    def subsetStringHelpUrl(self) -> str:
        return "https://gdal.org/drivers/vector/gpkg.html"

    def subsetString(self) -> str:
        return self._subset

    def setSubsetString(self, subset: str, updateFeatureCount: bool = True) -> bool:
        if self._cache_provider is not None:
            if not self._cache_provider.setSubsetString(subset, updateFeatureCount):
                return False
        self._subset = subset
        # Kept in the URI so it survives saving and reopening the project
        parts = decode_uri(self.dataSourceUri())
        parts["subset"] = subset
        self.setDataSourceUri(encode_uri(parts))
        self.clearMinMaxCache()
        self.dataChanged.emit()
        return True

    # --- Editing ------------------------------------------------------------

    def _edit(self, what: str, fn) -> bool:
        """Run fn (API calls + cache update). Errors go to pushError."""
        self._in_edit = True
        try:
            fn()
            return True
        except Exception as e:
            message = str(e) if isinstance(e, _EditError) else _describe(e)
            _log(f"{what} on {self._name} failed: {message}", Qgis.Warning)
            self.pushError(message)
            return False
        finally:
            self._in_edit = False
            self._schedule_reload()
            self.sync()

    def _write_cache(self, rows, deleted_ids=(), partial=False) -> None:
        """Mirror a saved edit into the cache so the layer shows it at once."""
        # Before the write, so a running sync cannot write older data over it
        local_cache.vector.note_local_edit(self._vector_id)
        cache = local_cache.vector.open_cache(self._vector_id)
        if cache is None:
            return
        try:
            local_cache.vector.write(cache.path, rows, deleted_ids, partial=partial)
        except Exception as e:
            # The server has the edit; the background sync brings it later
            _log(f"Cannot write edit to cache: {e}", Qgis.Warning)

    def _server_wkb(self, geometry: QgsGeometry) -> bytes:
        """WKB the server accepts: 2D, linear, single-part, of the layer type."""
        if geometry is None or geometry.isNull():
            raise _EditError(
                i18n.tr("Features without geometry cannot be saved to Kumoy.")
            )
        target = self.wkbType()
        if QgsWkbTypes.geometryType(geometry.wkbType()) != QgsWkbTypes.geometryType(
            target
        ):
            raise _EditError(
                i18n.tr("A {} geometry cannot be saved to a {} vector.").format(
                    QgsWkbTypes.displayString(geometry.wkbType()),
                    QgsWkbTypes.displayString(target),
                )
            )
        # Drops Z/M, segmentizes curves, and turns single <-> multi
        parts = geometry.coerceToType(target)
        if len(parts) != 1:
            raise _EditError(
                i18n.tr(
                    "A geometry with {} parts cannot be saved: Kumoy vectors hold "
                    "single-part geometries. Split it into separate features first."
                ).format(len(parts))
            )
        wkb = bytes(parts[0].asWkb())
        if len(wkb) * 4 / 3 > MAX_WKB_BASE64_LENGTH:
            raise _EditError(i18n.tr("A geometry is too large to save to Kumoy."))
        return wkb

    def _properties(self, values: Dict[int, object]) -> Dict[str, object]:
        """{field index: value} -> {column name: JSON value}, without kumoy_id."""
        return {
            self._fields.at(i).name(): _json_value(v)
            for i, v in values.items()
            if 0 < i < self._fields.count()
        }

    def addFeatures(self, flist, flags=None):
        features = list(flist)
        saved = 0

        def run():
            nonlocal saved
            rows = []
            for f in features:
                attrs = f.attributes()
                rows.append(
                    {
                        "kumoy_wkb": self._server_wkb(f.geometry()),
                        "properties": self._properties(dict(enumerate(attrs))),
                    }
                )
            for start in range(0, len(rows), MAX_ITEMS_PER_REQUEST):
                chunk = rows[start : start + MAX_ITEMS_PER_REQUEST]
                try:
                    ids = api.qgis_vector.add_features(
                        self._vector_id,
                        [
                            {
                                "kumoy_wkb": api.qgis_vector.encode_wkb(r["kumoy_wkb"]),
                                "properties": r["properties"],
                            }
                            for r in chunk
                        ],
                    )
                    if len(ids) != len(chunk):
                        raise AppError(
                            f"Server returned {len(ids)} ids for {len(chunk)} features"
                        )
                except Exception as e:
                    if saved:
                        raise _EditError(
                            i18n.tr("Only {} of {} new features were saved: {}").format(
                                saved, len(rows), _describe(e)
                            )
                        ) from e
                    raise
                for row, feature, new_id in zip(
                    chunk, features[start : start + len(chunk)], ids
                ):
                    row["kumoy_id"] = new_id
                    # QGIS reads the new ids back from the returned features
                    feature.setId(new_id)
                    if feature.attributeCount():
                        feature.setAttribute(0, new_id)
                self._write_cache(chunk)
                saved += len(chunk)

        ok = self._edit("Add features", run) if features else True
        return ok, features

    def deleteFeatures(self, ids) -> bool:
        ids = [int(i) for i in ids]

        def run():
            for start in range(0, len(ids), MAX_ITEMS_PER_REQUEST):
                chunk = ids[start : start + MAX_ITEMS_PER_REQUEST]
                api.qgis_vector.delete_features(self._vector_id, chunk)
                self._write_cache([], chunk)

        return self._edit("Delete features", run) if ids else True

    def changeAttributeValues(self, attr_map) -> bool:
        items = []
        for fid, values in attr_map.items():
            properties = self._properties(values)
            if properties:
                items.append({"kumoy_id": int(fid), "properties": properties})

        def run():
            for start in range(0, len(items), MAX_ITEMS_PER_REQUEST):
                chunk = items[start : start + MAX_ITEMS_PER_REQUEST]
                api.qgis_vector.change_attribute_values(self._vector_id, chunk)
                self._write_cache(chunk, partial=True)

        return self._edit("Change attributes", run) if items else True

    def changeGeometryValues(self, geometry_map) -> bool:
        def run():
            items = [
                {"kumoy_id": int(fid), "kumoy_wkb": self._server_wkb(geometry)}
                for fid, geometry in geometry_map.items()
            ]
            for start in range(0, len(items), MAX_ITEMS_PER_REQUEST):
                chunk = items[start : start + MAX_ITEMS_PER_REQUEST]
                api.qgis_vector.change_geometry_values(
                    self._vector_id,
                    [
                        {
                            "kumoy_id": i["kumoy_id"],
                            "kumoy_wkb": api.qgis_vector.encode_wkb(i["kumoy_wkb"]),
                        }
                        for i in chunk
                    ],
                )
                self._write_cache(chunk, partial=True)

        return self._edit("Change geometries", run) if geometry_map else True

    def addAttributes(self, attributes) -> bool:
        fields = [QgsField(f) for f in attributes]

        def run():
            columns = [
                Column(f.name(), _SERVER_TYPES.get(f.type(), "string")) for f in fields
            ]
            api.qgis_vector.add_attributes(
                self._vector_id, [{"name": c.name, "type": c.type} for c in columns]
            )
            # QGIS re-reads fields() right after this, before any sync
            self._added_fields.update({f.name(): f for f in fields})
            self._set_columns(self._columns + columns)
            self._schema_ahead = True

        return self._edit("Add attributes", run) if fields else True

    def deleteAttributes(self, attribute_ids) -> bool:
        indexes = sorted(int(i) for i in attribute_ids)

        def run():
            if 0 in indexes:
                raise _EditError(i18n.tr("The kumoy_id field cannot be deleted."))
            names = [self._fields.at(i).name() for i in indexes]
            api.qgis_vector.delete_attributes(self._vector_id, names)
            self._set_columns([c for c in self._columns if c.name not in names])
            self._schema_ahead = True

        return self._edit("Delete attributes", run) if indexes else True

    # --- Native types -------------------------------------------------------

    def _set_native_types(self) -> None:
        # Limits of the server's PostgreSQL columns
        self.setNativeTypes(
            [
                QgsVectorDataProvider.NativeType("Integer", "INTEGER", _T.LongLong),
                QgsVectorDataProvider.NativeType(
                    "Double Precision", "DOUBLE PRECISION", _T.Double, 0, 0, 0, 15
                ),
                QgsVectorDataProvider.NativeType("Boolean", "BOOLEAN", _T.Bool),
                QgsVectorDataProvider.NativeType(
                    "Varchar",
                    "VARCHAR",
                    _T.QString,
                    constants.MAX_CHARACTERS_STRING_FIELD,
                    constants.MAX_CHARACTERS_STRING_FIELD,
                ),
            ]
        )
