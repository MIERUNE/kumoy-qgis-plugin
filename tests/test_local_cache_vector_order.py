"""_update_existing_cache が columns 順序ズレに対して堅牢であることを検証する.

サーバーが返す columns の順序と既存 GPKG の物理カラム順が異なっていても、
属性値が破損しない（名前ベースで正しく書き込まれる）ことを検証する。
"""

import os

import pytest
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant


def _build_fields(spec):
    """spec: list of (name, QVariant_type) → QgsFields."""
    fs = QgsFields()
    for name, qtype in spec:
        fs.append(QgsField(name, qtype))
    return fs


def _create_initial_gpkg(path: str, fields: QgsFields, initial_records: list) -> None:
    """物理順 = fields の順序で GPKG を生成し、初期レコードを書き込む."""
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
    for rec in initial_records:
        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromWkt("POINT(0 0)"))
        feat.setFields(fields)
        for name in fields.names():
            feat[name] = rec[name]
        feat.setValid(True)
        writer.addFeature(feat)
    del writer


@pytest.mark.usefixtures("qgis_plugin_path")
class TestUpdateExistingCacheOrder:
    def _get_fn(self):
        from plugin_dir.kumoy.local_cache.vector import _update_existing_cache

        return _update_existing_cache

    def test_reversed_server_order_does_not_corrupt_values(self, tmp_path):
        """サーバーが返す columns 順を逆転しても、値が正しいカラムに書き込まれる."""
        cache_file = str(tmp_path / "v.gpkg")

        # 物理順 [kumoy_id, a, b] で既存 GPKG を作成（初期データ 1 行）
        initial_fields = _build_fields(
            [
                ("kumoy_id", QVariant.LongLong),
                ("a", QVariant.String),
                ("b", QVariant.LongLong),
            ]
        )
        _create_initial_gpkg(
            cache_file,
            initial_fields,
            [{"kumoy_id": 1, "a": "OLD_A", "b": 100}],
        )

        # サーバ最新順を逆転 [kumoy_id, b, a] で fields を構築
        server_fields = _build_fields(
            [
                ("kumoy_id", QVariant.LongLong),
                ("b", QVariant.LongLong),
                ("a", QVariant.String),
            ]
        )

        wkb = QgsGeometry.fromWkt("POINT(1 1)").asWkb()
        diff = {
            "deletedRows": [],
            "updatedRows": [
                {
                    "kumoy_id": 1,
                    "kumoy_wkb": bytes(wkb),
                    "properties": {"a": "VAL_A", "b": 99},
                }
            ],
        }

        self._get_fn()(cache_file, server_fields, diff)

        # 結果検証: a 列に "VAL_A"、b 列に 99 が入っているべき
        layer = QgsVectorLayer(cache_file, "v", "ogr")
        assert layer.isValid()
        feats = list(layer.getFeatures())
        assert len(feats) == 1
        feat = feats[0]
        assert feat["a"] == "VAL_A"
        assert feat["b"] == 99
        assert feat["kumoy_id"] == 1
        del layer
        # ファイルロック解放のため明示的に削除
        if os.path.exists(cache_file):
            pass

    def test_new_column_with_missing_property_is_null(self, tmp_path):
        """サーバが新カラムを追加したが、当該行の properties にキーが無くても KeyError にならない."""
        cache_file = str(tmp_path / "v.gpkg")

        initial_fields = _build_fields(
            [
                ("kumoy_id", QVariant.LongLong),
                ("a", QVariant.String),
            ]
        )
        _create_initial_gpkg(
            cache_file,
            initial_fields,
            [{"kumoy_id": 1, "a": "OLD_A"}],
        )

        # サーバ側で c カラムが追加された
        server_fields = _build_fields(
            [
                ("kumoy_id", QVariant.LongLong),
                ("a", QVariant.String),
                ("c", QVariant.String),
            ]
        )

        wkb = QgsGeometry.fromWkt("POINT(2 2)").asWkb()
        diff = {
            "deletedRows": [],
            "updatedRows": [
                {
                    "kumoy_id": 1,
                    "kumoy_wkb": bytes(wkb),
                    "properties": {"a": "VAL_A"},  # c が欠損
                }
            ],
        }

        # KeyError が発生しないこと
        self._get_fn()(cache_file, server_fields, diff)

        layer = QgsVectorLayer(cache_file, "v", "ogr")
        assert layer.isValid()
        feats = list(layer.getFeatures())
        assert len(feats) == 1
        feat = feats[0]
        assert feat["a"] == "VAL_A"
        # c は NULL（None または NULL QVariant）
        c_value = feat["c"]
        assert c_value is None or (hasattr(c_value, "isNull") and c_value.isNull())

    def test_deleted_column_is_removed(self, tmp_path):
        """サーバ側でカラムが削除された場合、キャッシュからも削除され、他列値は破損しない."""
        cache_file = str(tmp_path / "v.gpkg")

        initial_fields = _build_fields(
            [
                ("kumoy_id", QVariant.LongLong),
                ("a", QVariant.String),
                ("b", QVariant.LongLong),
            ]
        )
        _create_initial_gpkg(
            cache_file,
            initial_fields,
            [{"kumoy_id": 1, "a": "OLD_A", "b": 100}],
        )

        # サーバで b カラムが削除された
        server_fields = _build_fields(
            [
                ("kumoy_id", QVariant.LongLong),
                ("a", QVariant.String),
            ]
        )

        wkb = QgsGeometry.fromWkt("POINT(3 3)").asWkb()
        diff = {
            "deletedRows": [],
            "updatedRows": [
                {
                    "kumoy_id": 1,
                    "kumoy_wkb": bytes(wkb),
                    "properties": {"a": "VAL_A"},
                }
            ],
        }

        self._get_fn()(cache_file, server_fields, diff)

        layer = QgsVectorLayer(cache_file, "v", "ogr")
        assert layer.isValid()
        assert "b" not in layer.fields().names()
        feats = list(layer.getFeatures())
        assert len(feats) == 1
        assert feats[0]["a"] == "VAL_A"
