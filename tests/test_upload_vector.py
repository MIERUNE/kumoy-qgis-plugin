"""_get_geometry_type / _create_attribute_list のユニットテスト（QGIS環境が必要）"""

import unittest

import pytest
from qgis.core import (
    QgsField,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant


@pytest.mark.usefixtures("qgis_plugin_path")
class TestGetGeometryType(unittest.TestCase):
    """_get_geometry_type が各WKBタイプを正しくマッピングすること"""

    def _get_fn(self):
        from plugin_dir.processing.upload_vector.algorithm import _get_geometry_type

        return _get_geometry_type

    def test_point(self):
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "t", "memory")
        self.assertEqual(self._get_fn()(layer), "POINT")

    def test_multipoint(self):
        layer = QgsVectorLayer("MultiPoint?crs=EPSG:4326", "t", "memory")
        self.assertEqual(self._get_fn()(layer), "POINT")

    def test_linestring(self):
        layer = QgsVectorLayer("LineString?crs=EPSG:4326", "t", "memory")
        self.assertEqual(self._get_fn()(layer), "LINESTRING")

    def test_multilinestring(self):
        layer = QgsVectorLayer("MultiLineString?crs=EPSG:4326", "t", "memory")
        self.assertEqual(self._get_fn()(layer), "LINESTRING")

    def test_polygon(self):
        layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "t", "memory")
        self.assertEqual(self._get_fn()(layer), "POLYGON")

    def test_multipolygon(self):
        layer = QgsVectorLayer("MultiPolygon?crs=EPSG:4326", "t", "memory")
        self.assertEqual(self._get_fn()(layer), "POLYGON")

    def test_pointz(self):
        layer = QgsVectorLayer("PointZ?crs=EPSG:4326", "t", "memory")
        self.assertEqual(self._get_fn()(layer), "POINT")

    def test_polygonz(self):
        layer = QgsVectorLayer("PolygonZ?crs=EPSG:4326", "t", "memory")
        self.assertEqual(self._get_fn()(layer), "POLYGON")

    def test_unsupported_returns_none(self):
        layer = QgsVectorLayer("None?crs=EPSG:4326", "t", "memory")
        self.assertIsNone(self._get_fn()(layer))


@pytest.mark.usefixtures("qgis_plugin_path")
class TestCreateAttributeList(unittest.TestCase):
    """_create_attribute_list がQgsFieldの型を正しくマッピングすること"""

    def _get_fn(self):
        from plugin_dir.processing.upload_vector.algorithm import _create_attribute_list

        return _create_attribute_list

    def _make_layer(self, fields: list[tuple[str, QVariant.Type]]) -> QgsVectorLayer:
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "t", "memory")
        dp = layer.dataProvider()
        for name, qtype in fields:
            dp.addAttributes([QgsField(name, qtype)])
        layer.updateFields()
        return layer

    def test_string_field(self):
        layer = self._make_layer([("name", QVariant.String)])
        result = self._get_fn()(layer)
        self.assertEqual(result, [{"name": "name", "type": "string"}])

    def test_integer_field(self):
        layer = self._make_layer([("count", QVariant.Int)])
        result = self._get_fn()(layer)
        self.assertEqual(result, [{"name": "count", "type": "integer"}])

    def test_longlong_field(self):
        layer = self._make_layer([("big", QVariant.LongLong)])
        result = self._get_fn()(layer)
        self.assertEqual(result, [{"name": "big", "type": "integer"}])

    def test_double_field(self):
        layer = self._make_layer([("area", QVariant.Double)])
        result = self._get_fn()(layer)
        self.assertEqual(result, [{"name": "area", "type": "float"}])

    def test_bool_field(self):
        layer = self._make_layer([("flag", QVariant.Bool)])
        result = self._get_fn()(layer)
        self.assertEqual(result, [{"name": "flag", "type": "boolean"}])

    def test_multiple_fields(self):
        layer = self._make_layer(
            [
                ("name", QVariant.String),
                ("value", QVariant.Int),
                ("rate", QVariant.Double),
            ]
        )
        result = self._get_fn()(layer)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["name"], "name")
        self.assertEqual(result[1]["type"], "integer")
        self.assertEqual(result[2]["type"], "float")

    def test_empty_layer(self):
        layer = self._make_layer([])
        result = self._get_fn()(layer)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
