"""Local GeoPackage cache of vector features (file operations only).

Each vector has a directory of versioned files `{n}.gpkg`. A file is complete
once its `kumoy_meta` table holds the sync state (server metadata of the
vector + `last_updated`); that row is written in the same transaction as the
last rows, so a crash or cancel never exposes a half-written cache. The newest
complete file is the current one.

A full rebuild writes a new version instead of rewriting the current file:
providers keep reading the old one meanwhile, and on Windows a file that QGIS
still has open cannot be replaced. Older versions are deleted lazily by
`cleanup()` (failures are retried at the next sync).

Fetching from the server and scheduling live in kumoy/provider/dataprovider.py.
"""

import contextlib
import dataclasses
import json
import os
import re
import shutil
import sqlite3
import threading
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional

from osgeo import gdal, ogr, osr
from qgis.core import Qgis, QgsApplication, QgsMessageLog

from ..api.models import VectorDetail, from_dict
from ..constants import LOG_CATEGORY
from .size import dir_total_size

LAYER_NAME = "features"
_META_TABLE = "kumoy_meta"
_VERSION_FILE = re.compile(r"^(\d+)\.gpkg$")
_SIDE_SUFFIXES = ("", "-wal", "-shm", "-journal")

_GEOMETRY_TYPES = {
    "POINT": ogr.wkbPoint,
    "LINESTRING": ogr.wkbLineString,
    "POLYGON": ogr.wkbPolygon,
}

# Writes to one file from two connections fail with SQLITE_BUSY instead of
# waiting. ponytail: one lock for all vectors; writes are short transactions
# (a page or a diff), make it per vector if that ever shows up as contention.
_write_lock = threading.Lock()


@dataclass
class Cache:
    path: str
    vector: VectorDetail  # server metadata as of the last sync
    last_updated: str  # server time to pass to get-diff next time


def _root_dir() -> str:
    path = os.path.join(
        QgsApplication.qgisSettingsDirPath(), "kumoygis", "local_cache", "vectors"
    )
    os.makedirs(path, exist_ok=True)
    return path


def _vector_dir(vector_id: str) -> str:
    return os.path.join(_root_dir(), vector_id)


def _versions(vector_id: str) -> List[int]:
    """Version numbers of the vector's files, newest first."""
    try:
        names = os.listdir(_vector_dir(vector_id))
    except FileNotFoundError:
        return []
    found = [_VERSION_FILE.match(n) for n in names]
    return sorted((int(m.group(1)) for m in found if m), reverse=True)


def _path(vector_id: str, version: int) -> str:
    return os.path.join(_vector_dir(vector_id), f"{version}.gpkg")


def ogr_uri(path: str) -> str:
    """URI for the QGIS "ogr" provider (the file also holds the meta table)."""
    return f"{path}|layername={LAYER_NAME}"


def _read_meta(path: str) -> Optional[dict]:
    try:
        # closing(): sqlite3's own context manager commits but does not close,
        # and an open connection keeps the -wal/-shm files (and Windows locks)
        with contextlib.closing(sqlite3.connect(path)) as con:
            row = con.execute(
                "SELECT value FROM kumoy_meta WHERE fid = 1"  # = _META_TABLE
            ).fetchone()
    except sqlite3.Error:
        return None  # not a cache file, or still being built
    return json.loads(row[0]) if row else None


def open_cache(vector_id: str) -> Optional[Cache]:
    """The newest complete cache of the vector, or None."""
    for version in _versions(vector_id):
        path = _path(vector_id, version)
        meta = _read_meta(path)
        if meta is None:
            continue
        try:
            vector = from_dict(VectorDetail, meta["vector"])
            return Cache(path, vector, meta["last_updated"])
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _check(code, what: str) -> None:
    # GDAL returns error codes unless some code enabled exceptions globally;
    # in that mode the call itself raises and this never sees a failure
    if code not in (0, None):
        raise RuntimeError(f"{what}: {gdal.GetLastErrorMsg()}")


def _field_defn(name: str, column_type: str) -> ogr.FieldDefn:
    if column_type == "integer":
        return ogr.FieldDefn(name, ogr.OFTInteger64)
    if column_type == "float":
        return ogr.FieldDefn(name, ogr.OFTReal)
    if column_type == "boolean":
        defn = ogr.FieldDefn(name, ogr.OFTInteger)
        defn.SetSubType(ogr.OFSTBoolean)
        return defn
    return ogr.FieldDefn(name, ogr.OFTString)


def create(vector: VectorDetail) -> str:
    """Create an empty, not yet complete cache version and return its path.

    Fill it with write(); the write that passes `last_updated` completes it.
    """
    os.makedirs(_vector_dir(vector.id), exist_ok=True)
    versions = _versions(vector.id)
    path = _path(vector.id, (versions[0] + 1) if versions else 1)
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(path)
    if ds is None:
        raise RuntimeError(f"Cannot create {path}: {gdal.GetLastErrorMsg()}")
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    # kumoy_id as FID: QGIS's ogr provider then exposes it as the first field
    # and uses it as the feature id, matching the Kumoy provider's fields
    layer = ds.CreateLayer(
        LAYER_NAME,
        srs,
        _GEOMETRY_TYPES.get(vector.type, ogr.wkbUnknown),
        options=["FID=kumoy_id"],
    )
    if layer is None:
        raise RuntimeError(f"Cannot create layer in {path}: {gdal.GetLastErrorMsg()}")
    for column in vector.columns:
        _check(layer.CreateField(_field_defn(column.name, column.type)), "CreateField")
    meta = ds.CreateLayer(_META_TABLE, geom_type=ogr.wkbNone)
    _check(meta.CreateField(ogr.FieldDefn("value", ogr.OFTString)), "CreateField")
    # WAL: render threads keep reading while a sync writes (persistent setting)
    ds.ExecuteSQL("PRAGMA journal_mode=WAL")
    ds = None
    return path


def write(
    path: str,
    rows: Iterable[Dict],
    deleted_ids: Iterable[int] = (),
    vector: Optional[VectorDetail] = None,
    last_updated: Optional[str] = None,
    partial: bool = False,
    precondition: Optional[Callable[[], bool]] = None,
) -> bool:
    """Apply rows and deletions to a cache file in one transaction.

    rows: {"kumoy_id", "kumoy_wkb": bytes, "properties": {...}}. By default
    each row replaces the feature (or adds it). With partial=True a row only
    updates the keys it has, and rows of features not in the cache are
    skipped (local edits of features the cache does not know yet).
    Properties without a column in the file are ignored.

    Passing `last_updated` (with `vector`) stores the sync state, which also
    marks a new version complete.

    `precondition` is checked under the write lock, so no other write can
    slip in between; when it returns False nothing is written and this
    returns False.
    """
    with _write_lock:
        if precondition is not None and not precondition():
            return False
        ds = ogr.Open(path, 1)
        if ds is None:
            raise RuntimeError(f"Cannot open {path}: {gdal.GetLastErrorMsg()}")
        try:
            layer = ds.GetLayerByName(LAYER_NAME)
            defn = layer.GetLayerDefn()
            names = {
                defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())
            }
            _check(ds.StartTransaction(), "StartTransaction")
            try:
                for fid in deleted_ids:
                    # DeleteFeature on a missing id is an error (or an exception)
                    if layer.GetFeature(fid) is not None:
                        _check(layer.DeleteFeature(fid), "DeleteFeature")
                for row in rows:
                    _write_row(layer, defn, names, row, partial)
                if last_updated is not None:
                    _write_meta(ds, vector, last_updated)
                _check(ds.CommitTransaction(), "CommitTransaction")
            except BaseException:
                ds.RollbackTransaction()
                raise
        finally:
            ds = None
    return True


def _write_row(layer, defn, names, row: Dict, partial: bool) -> None:
    fid = int(row["kumoy_id"])
    if partial:
        feature = layer.GetFeature(fid)
        if feature is None:
            return
    else:
        feature = ogr.Feature(defn)
        feature.SetFID(fid)
    wkb = row.get("kumoy_wkb")
    if wkb is not None:
        geometry = ogr.CreateGeometryFromWkb(bytes(wkb))
        if geometry is None:
            raise RuntimeError(f"Invalid geometry of feature {fid}")
        feature.SetGeometry(geometry)
    for name, value in (row.get("properties") or {}).items():
        if name not in names:
            continue
        if value is None:
            feature.SetFieldNull(name)
        else:
            feature.SetField(name, value)
    if partial:
        _check(layer.SetFeature(feature), "SetFeature")
    else:
        _check(layer.UpsertFeature(feature), "UpsertFeature")


def _write_meta(ds, vector: Optional[VectorDetail], last_updated: str) -> None:
    if vector is None:
        raise ValueError("vector is required with last_updated")
    layer = ds.GetLayerByName(_META_TABLE)
    feature = ogr.Feature(layer.GetLayerDefn())
    feature.SetFID(1)
    value = {"vector": dataclasses.asdict(vector), "last_updated": last_updated}
    feature.SetField("value", json.dumps(value))
    _check(layer.UpsertFeature(feature), "UpsertFeature")


def _remove(path: str) -> bool:
    ok = True
    for suffix in _SIDE_SUFFIXES:
        try:
            os.unlink(path + suffix)
        except FileNotFoundError:
            pass
        except OSError as e:
            # Windows: still open in QGIS (a layer or the ogr connection pool)
            QgsMessageLog.logMessage(
                f"Cannot delete {path + suffix} yet: {e}", LOG_CATEGORY, Qgis.Info
            )
            ok = False
    return ok


def cleanup(vector_id: str, keep: Iterable[str] = ()) -> None:
    """Delete the vector's files except the current version and `keep`.

    Only call this while no sync of the vector runs: an unfinished rebuild
    looks like garbage. Files that are still open stay for the next call.
    """
    current = open_cache(vector_id)
    keep = set(keep) | ({current.path} if current else set())
    for version in _versions(vector_id):
        path = _path(vector_id, version)
        if path not in keep:
            _remove(path)
    # Cache files of plugin versions before the versioned layout
    _remove(os.path.join(_root_dir(), f"{vector_id}.gpkg"))


def clear(vector_id: str) -> bool:
    """Delete the vector's cache. False when some file is still in use."""
    ok = _remove(os.path.join(_root_dir(), f"{vector_id}.gpkg"))
    directory = _vector_dir(vector_id)
    try:
        # A partial failure is safe: each remaining file is a consistent
        # cache with its own last_updated
        shutil.rmtree(directory)
    except FileNotFoundError:
        pass
    except OSError as e:
        QgsMessageLog.logMessage(
            f"Cannot delete {directory}: {e}", LOG_CATEGORY, Qgis.Info
        )
        ok = False
    return ok


def clear_all() -> bool:
    """Delete all vector caches. False when some file is still in use."""
    ok = True
    for entry in list(os.scandir(_root_dir())):
        try:
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path)
            else:
                os.unlink(entry.path)
        except OSError as e:
            QgsMessageLog.logMessage(
                f"Cannot delete {entry.path}: {e}", LOG_CATEGORY, Qgis.Info
            )
            ok = False
    return ok


def get_cache_size(vector_id: str) -> int:
    """Size in bytes of the vector's cache files (0 when not cached)."""
    size = 0
    legacy = os.path.join(_root_dir(), f"{vector_id}.gpkg")
    for suffix in _SIDE_SUFFIXES:
        if os.path.isfile(legacy + suffix):
            size += os.path.getsize(legacy + suffix)
    directory = _vector_dir(vector_id)
    if os.path.isdir(directory):
        size += dir_total_size(directory)
    return size


def get_total_cache_size() -> int:
    """Size in bytes of all vector cache files."""
    return dir_total_size(_root_dir())
