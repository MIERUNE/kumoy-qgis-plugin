from unittest.mock import Mock

from qgis.core import QgsRasterLayer
from qgis.testing import QgisTestCase, start_app

from qgishub.qgisproject.check import CompatibilityChecker


class TestRasterLayerChecker(QgisTestCase):
    """Test cases for RasterLayerChecker"""

    @classmethod
    def setUpClass(cls):
        """Initialize QGIS application using qgis.testing"""
        super().setUpClass()
        start_app()

    def create_gdal_raster_layer(self):
        """Create a GDAL raster layer for testing"""
        # Create a minimal raster layer URI for GDAL provider
        layer = QgsRasterLayer("", "test_raster", "gdal")

        # Mock the data provider to return 'gdal' as name
        mock_provider = Mock()
        mock_provider.name.return_value = "gdal"
        layer.dataProvider = lambda: mock_provider

        return layer

    def create_wms_layer(self, uri_params):
        """Create a WMS raster layer with specified URI parameters"""
        # Create WMS layer
        layer = QgsRasterLayer("", "test_wms", "wms")

        # Mock the data provider to return 'wms' as name and custom URI
        mock_provider = Mock()
        mock_provider.name.return_value = "wms"
        mock_provider.dataSourceUri.return_value = uri_params
        layer.dataProvider = lambda: mock_provider

        return layer

    def create_xyzvectortiles_layer(self, uri_params=None):
        """Create an xyzvectortiles layer for testing vector tiles"""
        # Use provided URI params or default GSI vector tile URL
        if uri_params is None:
            vector_tile_url = "type=xyz&amp;url=https://cyberjapandata.gsi.go.jp/xyz/experimental_bvmap/%7Bz%7D/%7Bx%7D/%7By%7D.pbf&amp;zmax=16&amp;zmin=0&amp;http-header:referer="
            uri_params = f"url={vector_tile_url}"

        layer = QgsRasterLayer("", "test_vector_tiles", "xyzvectortiles")

        # Mock the data provider to return 'xyzvectortiles' as name and custom URI
        mock_provider = Mock()
        mock_provider.name.return_value = "xyzvectortiles"
        mock_provider.dataSourceUri.return_value = uri_params
        layer.dataProvider = lambda: mock_provider

        return layer

    def test_non_wms_provider(self):
        """Test that non-WMS providers are not supported"""
        layer = self.create_gdal_raster_layer()

        is_compatible, reason = CompatibilityChecker.raster.check(layer)

        self.assertFalse(is_compatible)
        self.assertEqual(reason, " - raster provider not supported")

    def test_wms_xyz_type(self):
        """Test WMS layer with XYZ type"""
        layer = self.create_wms_layer(
            "tilePixelRatio=1&amp;type=xyz&amp;url=https://tile.openstreetmap.org/%7Bz%7D/%7Bx%7D/%7By%7D.png&amp;zmax=19&amp;zmin=0"
        )

        is_compatible, reason = CompatibilityChecker.raster.check(layer)

        self.assertTrue(is_compatible)
        self.assertEqual(reason, "")

    def test_wms_xyz_type_uppercase(self):
        """Test WMS layer with XYZ type in uppercase"""
        layer = self.create_wms_layer(
            "tilePixelRatio=1&amp;type=XYZ&amp;url=https://tile.openstreetmap.org/%7Bz%7D/%7Bx%7D/%7By%7D.png&amp;zmax=19&amp;zmin=0"
        )

        is_compatible, reason = CompatibilityChecker.raster.check(layer)

        self.assertTrue(is_compatible)
        self.assertEqual(reason, "")

    def test_wms_non_xyz_type(self):
        """Test WMS layer without XYZ type"""
        layer = self.create_wms_layer("url=http://example.com&param=value")

        is_compatible, reason = CompatibilityChecker.raster.check(layer)

        self.assertFalse(is_compatible)
        self.assertEqual(reason, " - only XYZ type WMS supported")

    def test_xyzvectortiles_provider(self):
        """Test that xyzvectortiles provider is not supported"""
        layer = self.create_xyzvectortiles_layer()

        is_compatible, reason = CompatibilityChecker.raster.check(layer)

        self.assertFalse(is_compatible)
        self.assertEqual(reason, " - raster provider not supported")


if __name__ == "__main__":
    import unittest

    unittest.main()
