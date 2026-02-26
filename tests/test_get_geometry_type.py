"""QGIS依存テストの例: メモリレイヤーのジオメトリタイプ判定"""

import importlib.util
import unittest
from pathlib import Path

from qgis.core import QgsVectorLayer, QgsWkbTypes

# processing パッケージの __init__.py を経由すると相対importで失敗するため、
# モジュールを直接ロードする
_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "processing"
    / "upload_vector"
    / "algorithm.py"
)
_spec = importlib.util.spec_from_file_location("algorithm_module", _MODULE_PATH)
assert _spec is not None
_module = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_module)
_get_geometry_type = _module._get_geometry_type


class TestGetGeometryType(unittest.TestCase):
    def test_point(self):
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "test", "memory")
        self.assertEqual(_get_geometry_type(layer), "POINT")

    def test_multipoint(self):
        layer = QgsVectorLayer("MultiPoint?crs=EPSG:4326", "test", "memory")
        self.assertEqual(_get_geometry_type(layer), "POINT")

    def test_linestring(self):
        layer = QgsVectorLayer("LineString?crs=EPSG:4326", "test", "memory")
        self.assertEqual(_get_geometry_type(layer), "LINESTRING")

    def test_multilinestring(self):
        layer = QgsVectorLayer("MultiLineString?crs=EPSG:4326", "test", "memory")
        self.assertEqual(_get_geometry_type(layer), "LINESTRING")

    def test_polygon(self):
        layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "test", "memory")
        self.assertEqual(_get_geometry_type(layer), "POLYGON")

    def test_multipolygon(self):
        layer = QgsVectorLayer("MultiPolygon?crs=EPSG:4326", "test", "memory")
        self.assertEqual(_get_geometry_type(layer), "POLYGON")

    def test_point_z(self):
        layer = QgsVectorLayer("PointZ?crs=EPSG:4326", "test", "memory")
        self.assertEqual(_get_geometry_type(layer), "POINT")

    def test_no_geometry(self):
        layer = QgsVectorLayer("None", "test", "memory")
        self.assertIsNone(_get_geometry_type(layer))


if __name__ == "__main__":
    unittest.main()
