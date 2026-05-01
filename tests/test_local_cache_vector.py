"""kumoy/local_cache/vector.py のテスト

カラム順序チェック (_columns_match) と sync_local_cache の分岐挙動を検証する。
"""

import os
import types

import pytest
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorFileWriter,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant


def _build_fields(column_names):
    """kumoy_id 先頭 + 指定カラム名（全て String）の QgsFields を作る"""
    fs = QgsFields()
    fs.append(QgsField("kumoy_id", QVariant.LongLong))
    for name in column_names:
        fs.append(QgsField(name, QVariant.String))
    return fs


def _make_gpkg(path: str, column_names):
    """テスト用に直接 GPKG を生成する"""
    fields = _build_fields(column_names)
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.layerOptions = ["FID=kumoy_id"]
    options.driverName = "GPKG"
    options.fileEncoding = "UTF-8"
    writer = QgsVectorFileWriter.create(
        path,
        fields,
        QgsWkbTypes.Point,
        QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsProject.instance().transformContext(),
        options,
    )
    assert writer.hasError() == QgsVectorFileWriter.NoError
    del writer


def _point_wkb(x: float, y: float) -> bytes:
    g = QgsGeometry.fromPointXY(QgsPointXY(x, y))
    return bytes(g.asWkb())


@pytest.mark.usefixtures("qgis_plugin_path")
class TestColumnsMatch:
    def _fn(self):
        from plugin_dir.kumoy.local_cache.vector import _columns_match

        return _columns_match

    def test_same_order(self, tmp_path):
        gpkg = str(tmp_path / "x.gpkg")
        _make_gpkg(gpkg, ["a", "b", "c"])
        assert self._fn()(gpkg, _build_fields(["a", "b", "c"])) is True

    def test_swapped_order(self, tmp_path):
        gpkg = str(tmp_path / "x.gpkg")
        _make_gpkg(gpkg, ["a", "b", "c"])
        assert self._fn()(gpkg, _build_fields(["a", "c", "b"])) is False

    def test_extra_in_cache(self, tmp_path):
        gpkg = str(tmp_path / "x.gpkg")
        _make_gpkg(gpkg, ["a", "b", "c", "extra"])
        assert self._fn()(gpkg, _build_fields(["a", "b", "c"])) is False

    def test_extra_on_server(self, tmp_path):
        gpkg = str(tmp_path / "x.gpkg")
        _make_gpkg(gpkg, ["a", "b"])
        assert self._fn()(gpkg, _build_fields(["a", "b", "c"])) is False

    def test_only_kumoy_id(self, tmp_path):
        gpkg = str(tmp_path / "x.gpkg")
        _make_gpkg(gpkg, [])
        assert self._fn()(gpkg, _build_fields([])) is True

    def test_missing_file(self, tmp_path):
        gpkg = str(tmp_path / "missing.gpkg")
        assert self._fn()(gpkg, _build_fields(["a"])) is False


@pytest.mark.usefixtures("qgis_plugin_path")
class TestSyncLocalCache:
    """sync_local_cache の分岐挙動を検証する"""

    @pytest.fixture
    def sync_setup(self, tmp_path, monkeypatch):
        from plugin_dir.kumoy import api as real_api
        from plugin_dir.kumoy.local_cache import vector as vector_mod
        from plugin_dir.kumoy.local_cache.settings import (
            delete_last_updated,
            store_last_updated,
        )

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        monkeypatch.setattr(vector_mod, "_get_cache_dir", lambda: str(cache_dir))

        calls = {"get_features": 0, "get_diff": 0}

        def default_get_features(vector_id, after_id=None):
            return [
                {
                    "kumoy_id": 1,
                    "kumoy_wkb": _point_wkb(0.0, 0.0),
                    "properties": {"a": "v1", "b": "v2"},
                }
            ]

        def default_get_diff(vector_id, last_updated):
            return {"updatedRows": [], "deletedRows": []}

        state = {
            "get_features": default_get_features,
            "get_diff": default_get_diff,
        }

        fake_qgis_vector = types.SimpleNamespace(
            get_features=lambda **kwargs: (
                calls.__setitem__("get_features", calls["get_features"] + 1)
                or state["get_features"](**kwargs)
            ),
            get_diff=lambda *args, **kwargs: (
                calls.__setitem__("get_diff", calls["get_diff"] + 1)
                or state["get_diff"](*args, **kwargs)
            ),
        )
        fake_api = types.SimpleNamespace(
            qgis_vector=fake_qgis_vector,
            error=real_api.error,
        )
        monkeypatch.setattr(vector_mod, "api", fake_api)

        vector_id = "test-vec-1"
        delete_last_updated(vector_id)

        yield types.SimpleNamespace(
            vector_mod=vector_mod,
            cache_dir=str(cache_dir),
            vector_id=vector_id,
            calls=calls,
            state=state,
            store_last_updated=store_last_updated,
            delete_last_updated=delete_last_updated,
            real_api=real_api,
        )

        delete_last_updated(vector_id)

    def _gpkg_column_order(self, cache_file):
        from qgis.core import QgsVectorLayer

        layer = QgsVectorLayer(cache_file, "tmp", "ogr")
        names = [n for n in layer.fields().names() if n != "kumoy_id"]
        del layer
        return names

    def test_creates_new_cache_when_missing(self, sync_setup):
        s = sync_setup
        cache_file = os.path.join(s.cache_dir, f"{s.vector_id}.gpkg")
        assert not os.path.exists(cache_file)

        s.vector_mod.sync_local_cache(
            vector_id=s.vector_id,
            fields=_build_fields(["a", "b"]),
            geometry_type=QgsWkbTypes.Point,
        )

        assert os.path.exists(cache_file)
        assert s.calls["get_features"] >= 1
        assert s.calls["get_diff"] == 0
        assert self._gpkg_column_order(cache_file) == ["a", "b"]

    def test_uses_diff_when_order_matches(self, sync_setup):
        s = sync_setup
        cache_file = os.path.join(s.cache_dir, f"{s.vector_id}.gpkg")
        _make_gpkg(cache_file, ["a", "b"])
        s.store_last_updated(s.vector_id, "2025-01-01T00:00:00Z")

        s.vector_mod.sync_local_cache(
            vector_id=s.vector_id,
            fields=_build_fields(["a", "b"]),
            geometry_type=QgsWkbTypes.Point,
        )

        assert s.calls["get_diff"] == 1
        assert s.calls["get_features"] == 0
        assert self._gpkg_column_order(cache_file) == ["a", "b"]

    def test_recreates_when_order_differs(self, sync_setup):
        s = sync_setup
        cache_file = os.path.join(s.cache_dir, f"{s.vector_id}.gpkg")
        _make_gpkg(cache_file, ["b", "a"])
        s.store_last_updated(s.vector_id, "2025-01-01T00:00:00Z")

        s.vector_mod.sync_local_cache(
            vector_id=s.vector_id,
            fields=_build_fields(["a", "b"]),
            geometry_type=QgsWkbTypes.Point,
        )

        assert s.calls["get_diff"] == 0
        assert s.calls["get_features"] >= 1
        assert self._gpkg_column_order(cache_file) == ["a", "b"]

        from plugin_dir.kumoy.local_cache.settings import get_last_updated

        assert get_last_updated(s.vector_id) is not None

    def test_raises_when_clear_fails(self, sync_setup, monkeypatch):
        s = sync_setup
        cache_file = os.path.join(s.cache_dir, f"{s.vector_id}.gpkg")
        _make_gpkg(cache_file, ["b", "a"])
        s.store_last_updated(s.vector_id, "2025-01-01T00:00:00Z")

        monkeypatch.setattr(s.vector_mod, "clear", lambda vid: False)

        with pytest.raises(Exception, match="Failed to clear cache"):
            s.vector_mod.sync_local_cache(
                vector_id=s.vector_id,
                fields=_build_fields(["a", "b"]),
                geometry_type=QgsWkbTypes.Point,
            )

        assert s.calls["get_features"] == 0

    def test_recreates_on_max_diff_count_exceeded(self, sync_setup):
        s = sync_setup
        cache_file = os.path.join(s.cache_dir, f"{s.vector_id}.gpkg")
        _make_gpkg(cache_file, ["a", "b"])
        s.store_last_updated(s.vector_id, "2025-01-01T00:00:00Z")

        def raise_max_diff(vector_id, last_updated):
            raise s.real_api.error.AppError(
                "Application Error", "MAX_DIFF_COUNT_EXCEEDED"
            )

        s.state["get_diff"] = raise_max_diff

        s.vector_mod.sync_local_cache(
            vector_id=s.vector_id,
            fields=_build_fields(["a", "b"]),
            geometry_type=QgsWkbTypes.Point,
        )

        assert s.calls["get_diff"] == 1
        assert s.calls["get_features"] >= 1
        assert self._gpkg_column_order(cache_file) == ["a", "b"]
