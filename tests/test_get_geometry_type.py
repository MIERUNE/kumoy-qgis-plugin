import unittest

from qgis.core import QgsVectorLayer

from processing.upload_vector.algorithm import _get_geometry_type


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
