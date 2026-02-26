"""QGIS APIに依存する基本テスト。CIのQGIS環境が正しく動作することを検証する。"""

import unittest

import pytest
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsVectorLayer,
    QgsWkbTypes,
)


class TestQgisBasic(unittest.TestCase):
    def test_memory_layer_creation(self):
        """メモリレイヤーが正しく作成できること"""
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "test", "memory")
        self.assertTrue(layer.isValid())

    def test_memory_layer_geometry_type(self):
        """メモリレイヤーのジオメトリタイプが正しいこと"""
        point = QgsVectorLayer("Point?crs=EPSG:4326", "p", "memory")
        line = QgsVectorLayer("LineString?crs=EPSG:4326", "l", "memory")
        polygon = QgsVectorLayer("Polygon?crs=EPSG:4326", "pg", "memory")

        self.assertEqual(point.wkbType(), QgsWkbTypes.Point)
        self.assertEqual(line.wkbType(), QgsWkbTypes.LineString)
        self.assertEqual(polygon.wkbType(), QgsWkbTypes.Polygon)

    def test_crs(self):
        """CRSの生成と比較が正しく動作すること"""
        crs_4326 = QgsCoordinateReferenceSystem("EPSG:4326")
        crs_3857 = QgsCoordinateReferenceSystem("EPSG:3857")

        self.assertTrue(crs_4326.isValid())
        self.assertTrue(crs_3857.isValid())
        self.assertNotEqual(crs_4326, crs_3857)

    def test_memory_layer_with_fields(self):
        """フィールド付きメモリレイヤーが正しく作成できること"""
        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326&field=name:string&field=value:integer",
            "test",
            "memory",
        )
        self.assertTrue(layer.isValid())
        self.assertEqual(layer.fields().count(), 2)
        self.assertEqual(layer.fields().at(0).name(), "name")
        self.assertEqual(layer.fields().at(1).name(), "value")


@pytest.mark.usefixtures("qgis_plugin_path")
class TestPluginImport(unittest.TestCase):
    """プラグインモジュールがimportできることを検証する"""

    def test_import_get_geometry_type(self):
        from plugin_dir.processing.upload_vector.algorithm import _get_geometry_type

        layer = QgsVectorLayer("Point?crs=EPSG:4326", "test", "memory")
        self.assertEqual(_get_geometry_type(layer), "POINT")

    def test_import_constants(self):
        from plugin_dir.kumoy.constants import PLUGIN_NAME

        self.assertIsInstance(PLUGIN_NAME, str)


if __name__ == "__main__":
    unittest.main()
