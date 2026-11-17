"""kumoy/local_cache/vector.py: versioned GeoPackage cache files."""

import os
import types

import pytest
from qgis.core import QgsGeometry, QgsPointXY, QgsVectorLayer


def _wkb(x: float, y: float) -> bytes:
    return bytes(QgsGeometry.fromPointXY(QgsPointXY(x, y)).asWkb())


def _row(fid, x=0.0, **props):
    return {"kumoy_id": fid, "kumoy_wkb": _wkb(x, 0.0), "properties": props}


@pytest.fixture
def cache(tmp_path, monkeypatch, qgis_plugin_path):
    from plugin_dir.kumoy.api.models import Column, VectorDetail
    from plugin_dir.kumoy.local_cache import vector

    root = tmp_path / "vectors"
    root.mkdir()
    monkeypatch.setattr(vector, "_root_dir", lambda: str(root))
    detail = VectorDetail(
        id="v1",
        name="vec",
        type="POINT",
        role="ADMIN",
        columns=[
            Column("name", "string"),
            Column("n", "integer"),
            Column("ok", "boolean"),
        ],
    )
    return types.SimpleNamespace(mod=vector, root=root, detail=detail)


def _features(path):
    from plugin_dir.kumoy.local_cache.vector import ogr_uri

    layer = QgsVectorLayer(ogr_uri(path), "t", "ogr")
    assert layer.isValid()
    return {f.id(): (f.geometry().asWkt(), f.attributes()) for f in layer.getFeatures()}


class TestCreateAndWrite:
    def test_new_version_is_incomplete_until_last_updated(self, cache):
        path = cache.mod.create(cache.detail)
        cache.mod.write(path, [_row(1, name="a", n=2, ok=True)])
        assert cache.mod.open_cache("v1") is None

        cache.mod.write(
            path, [], vector=cache.detail, last_updated="2026-01-01T00:00:00Z"
        )

        current = cache.mod.open_cache("v1")
        assert current.path == path
        assert current.last_updated == "2026-01-01T00:00:00Z"
        assert [c.name for c in current.vector.columns] == ["name", "n", "ok"]
        assert current.vector.role == "ADMIN"
        assert _features(path) == {1: ("Point (0 0)", [1, "a", 2, True])}

    def test_fields_follow_column_order_with_kumoy_id_first(self, cache):
        path = cache.mod.create(cache.detail)
        layer = QgsVectorLayer(cache.mod.ogr_uri(path), "t", "ogr")
        assert layer.fields().names() == ["kumoy_id", "name", "n", "ok"]

    def test_failed_write_changes_nothing(self, cache):
        path = cache.mod.create(cache.detail)
        cache.mod.write(
            path, [_row(1, name="a")], vector=cache.detail, last_updated="t1"
        )

        bad = {"kumoy_id": 2, "kumoy_wkb": b"not wkb", "properties": {}}
        with pytest.raises(Exception):
            cache.mod.write(
                path, [_row(3), bad], [1], vector=cache.detail, last_updated="t2"
            )

        assert cache.mod.open_cache("v1").last_updated == "t1"
        assert list(_features(path)) == [1]

    def test_upsert_delete_and_unknown_properties(self, cache):
        path = cache.mod.create(cache.detail)
        cache.mod.write(path, [_row(1, name="a"), _row(2, name="b")])
        cache.mod.write(
            path,
            [_row(1, x=5, name="A", gone="ignored")],
            deleted_ids=[2, 99],  # 99 is not cached: ignored
        )
        assert _features(path) == {1: ("Point (5 0)", [1, "A", None, None])}

    def test_write_is_skipped_after_any_number_of_noted_edits(self, cache):
        path = cache.mod.create(cache.detail)
        cache.mod.write(path, [_row(1, name="a")])
        seen = cache.mod.local_edit_count("v1")

        # Two edits (e.g. two layers of the vector, or a Processing tool):
        # any change of the count means the fetched rows may be older
        cache.mod.note_local_edit("v1")
        cache.mod.note_local_edit("v1")
        assert not cache.mod.write(path, [_row(1, name="stale")], edits_seen=seen)
        assert _features(path)[1][1][1] == "a"

        # Edits of another vector do not matter
        seen = cache.mod.local_edit_count("v1")
        cache.mod.note_local_edit("v2")
        assert cache.mod.write(path, [_row(1, name="new")], edits_seen=seen)
        assert _features(path)[1][1][1] == "new"

    def test_partial_updates_only_given_keys(self, cache):
        path = cache.mod.create(cache.detail)
        cache.mod.write(path, [_row(1, name="a", n=1)])
        cache.mod.write(
            path,
            [
                {"kumoy_id": 1, "properties": {"n": 7}},
                {"kumoy_id": 5, "properties": {"n": 1}},  # not cached: skipped
            ],
            partial=True,
        )
        cache.mod.write(path, [{"kumoy_id": 1, "kumoy_wkb": _wkb(3, 3)}], partial=True)
        assert _features(path) == {1: ("Point (3 3)", [1, "a", 7, None])}


class TestVersions:
    def _complete(self, cache, last_updated):
        path = cache.mod.create(cache.detail)
        cache.mod.write(path, [], vector=cache.detail, last_updated=last_updated)
        return path

    def test_newest_complete_version_wins(self, cache):
        old = self._complete(cache, "t1")
        new = self._complete(cache, "t2")
        cache.mod.create(cache.detail)  # an unfinished rebuild
        assert old != new
        assert cache.mod.open_cache("v1").path == new

    def test_cleanup_keeps_current_and_in_use(self, cache):
        first = self._complete(cache, "t1")
        second = self._complete(cache, "t2")
        current = self._complete(cache, "t3")
        unfinished = cache.mod.create(cache.detail)
        legacy = cache.root / "v1.gpkg"
        legacy.write_bytes(b"old layout")

        cache.mod.cleanup("v1", keep=[second])

        assert not os.path.exists(first)
        assert os.path.exists(second)
        assert os.path.exists(current)
        assert not os.path.exists(unfinished)
        assert not legacy.exists()

    def test_cleanup_tolerates_locked_files(self, cache, monkeypatch):
        self._complete(cache, "t1")
        current = self._complete(cache, "t2")

        def locked(path):
            raise PermissionError(path)

        monkeypatch.setattr(cache.mod.os, "unlink", locked)
        cache.mod.cleanup("v1")  # Windows: retried at the next sync
        assert cache.mod.open_cache("v1").path == current


class TestClearAndSize:
    def test_size_and_clear(self, cache):
        assert cache.mod.get_cache_size("v1") == 0
        path = cache.mod.create(cache.detail)
        (cache.root / "v1.gpkg").write_bytes(b"x" * 10)  # legacy file
        (cache.root / "v2.gpkg").write_bytes(b"x" * 999)  # another vector

        size = cache.mod.get_cache_size("v1")
        assert size == os.path.getsize(path) + 10
        assert cache.mod.get_total_cache_size() == size + 999

        assert cache.mod.clear("v1") is True
        assert cache.mod.get_cache_size("v1") == 0
        assert cache.mod.open_cache("v1") is None
        assert (cache.root / "v2.gpkg").exists()

    def test_clear_missing_is_ok(self, cache):
        assert cache.mod.clear("nope") is True

    def test_clear_all(self, cache):
        cache.mod.create(cache.detail)
        (cache.root / "v2.gpkg").write_bytes(b"x")
        assert cache.mod.clear_all() is True
        assert list(cache.root.iterdir()) == []
        assert cache.mod.get_total_cache_size() == 0

    def test_clear_reports_locked_files(self, cache, monkeypatch):
        cache.mod.create(cache.detail)

        def locked(*args, **kwargs):
            raise PermissionError("locked")

        monkeypatch.setattr(cache.mod.shutil, "rmtree", locked)
        assert cache.mod.clear("v1") is False
