from unittest.mock import Mock, patch

from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsFillSymbol,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsRasterLayer,
    QgsSimpleFillSymbolLayer,
    QgsSimpleLineSymbolLayer,
    QgsSimpleMarkerSymbolLayer,
    QgsSingleSymbolRenderer,
    QgsSvgMarkerSymbolLayer,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.testing import QgisTestCase, start_app

from qgishub.qgisproject.check.layer import RasterLayerChecker, VectorLayerChecker


class TestVectorLayerChecker(QgisTestCase):
    """Test cases for VectorLayerChecker"""

    @classmethod
    def setUpClass(cls):
        """Initialize QGIS application using qgis.testing"""
        super().setUpClass()
        start_app()

    def create_memory_layer(self, geometry_type, provider_name="memory"):
        """Create a memory layer with specified geometry type using QGIS testing utilities"""
        # Define geometry type strings for memory provider
        geometry_strings = {
            QgsWkbTypes.PointGeometry: "Point",
            QgsWkbTypes.LineGeometry: "LineString",
            QgsWkbTypes.PolygonGeometry: "Polygon",
        }

        geometry_string = geometry_strings.get(geometry_type, "Point")
        layer = QgsVectorLayer(
            f"{geometry_string}?crs=epsg:4326", "test_layer", provider_name
        )

        # Ensure layer is valid
        self.assertTrue(layer.isValid(), f"Failed to create {geometry_string} layer")

        return layer

    def create_qgishub_layer(self, geometry_type):
        """Create a layer that mimics qgishub provider"""
        layer = self.create_memory_layer(geometry_type)

        # Create a mock data provider that returns 'qgishub' as name
        mock_provider = Mock()
        mock_provider.name.return_value = "qgishub"

        # Replace the layer's dataProvider method to return our mock
        layer.dataProvider = lambda: mock_provider

        return layer

    def set_simple_marker_renderer(self, layer: QgsVectorLayer):
        """Set SimpleMarker renderer on the layer"""
        symbol = QgsMarkerSymbol()
        symbol.deleteSymbolLayer(0)  # Remove default layer
        symbol.appendSymbolLayer(QgsSimpleMarkerSymbolLayer())
        renderer = QgsSingleSymbolRenderer(symbol)
        layer.setRenderer(renderer)

    def set_simple_line_renderer(self, layer: QgsVectorLayer):
        """Set SimpleLine renderer on the layer"""
        symbol = QgsLineSymbol()
        symbol.deleteSymbolLayer(0)  # Remove default layer
        symbol.appendSymbolLayer(QgsSimpleLineSymbolLayer())
        renderer = QgsSingleSymbolRenderer(symbol)
        layer.setRenderer(renderer)

    def set_simple_fill_renderer(self, layer: QgsVectorLayer):
        """Set SimpleFill renderer on the layer"""
        symbol = QgsFillSymbol()
        symbol.deleteSymbolLayer(0)  # Remove default layer
        symbol.appendSymbolLayer(QgsSimpleFillSymbolLayer())
        renderer = QgsSingleSymbolRenderer(symbol)
        layer.setRenderer(renderer)

    def set_svg_marker_renderer(self, layer: QgsVectorLayer):
        """Set SvgMarker renderer on the layer"""
        symbol = QgsMarkerSymbol()
        symbol.deleteSymbolLayer(0)  # Remove default layer
        svg_layer = QgsSvgMarkerSymbolLayer("circle.svg")  # Provide a default SVG path
        symbol.appendSymbolLayer(svg_layer)
        renderer = QgsSingleSymbolRenderer(symbol)
        layer.setRenderer(renderer)

    def set_categorized_renderer(self, layer: QgsVectorLayer):
        """Set categorized renderer on the layer"""
        renderer = QgsCategorizedSymbolRenderer()
        layer.setRenderer(renderer)

    def test_non_qgishub_provider(self):
        """Test that non-qgishub providers are not supported"""
        layer = self.create_memory_layer(QgsWkbTypes.PointGeometry)

        is_compatible, reason = VectorLayerChecker.check(layer)

        self.assertFalse(is_compatible)
        self.assertEqual(reason, " - generic vector data not supported")

    def test_no_renderer(self):
        """Test layer with no renderer"""
        layer = self.create_qgishub_layer(QgsWkbTypes.PointGeometry)
        layer.setRenderer(None)

        is_compatible, reason = VectorLayerChecker.check(layer)

        self.assertFalse(is_compatible)
        self.assertEqual(reason, " - no renderer found")

    def test_non_single_symbol_renderer(self):
        """Test that non-single symbol renderers are not supported"""
        layer = self.create_qgishub_layer(QgsWkbTypes.PointGeometry)
        self.set_categorized_renderer(layer)

        is_compatible, reason = VectorLayerChecker.check(layer)

        self.assertFalse(is_compatible)
        self.assertEqual(reason, " - categorizedSymbol renderer not supported")

    def test_point_layer_with_simple_marker(self):
        """Test point layer with SimpleMarker symbol"""
        layer = self.create_qgishub_layer(QgsWkbTypes.PointGeometry)
        self.set_simple_marker_renderer(layer)

        is_compatible, reason = VectorLayerChecker.check(layer)

        self.assertTrue(is_compatible)
        self.assertEqual(reason, "")

    def test_point_layer_with_unsupported_renderer(self):
        """Test point layer with unsupported renderer"""
        layer = self.create_qgishub_layer(QgsWkbTypes.PointGeometry)
        self.set_svg_marker_renderer(layer)

        is_compatible, reason = VectorLayerChecker.check(layer)

        self.assertFalse(is_compatible)
        self.assertEqual(reason, " - unsupported point renderer")

    def test_line_layer_with_simple_line(self):
        """Test line layer with SimpleLine symbol"""
        layer = self.create_qgishub_layer(QgsWkbTypes.LineGeometry)
        self.set_simple_line_renderer(layer)

        is_compatible, reason = VectorLayerChecker.check(layer)

        self.assertTrue(is_compatible)
        self.assertEqual(reason, "")

    def test_polygon_layer_with_simple_fill(self):
        """Test polygon layer with SimpleFill symbol"""
        layer = self.create_qgishub_layer(QgsWkbTypes.PolygonGeometry)
        self.set_simple_fill_renderer(layer)

        is_compatible, reason = VectorLayerChecker.check(layer)

        self.assertTrue(is_compatible)
        self.assertEqual(reason, "")

    def test_multiple_symbol_layers(self):
        """Test layer with multiple simple symbol layers - should be compatible"""
        layer = self.create_qgishub_layer(QgsWkbTypes.PointGeometry)

        # Create symbol with multiple compatible layers
        symbol = QgsMarkerSymbol()
        symbol.deleteSymbolLayer(0)  # Remove default layer
        symbol.appendSymbolLayer(QgsSimpleMarkerSymbolLayer())  # Compatible first
        symbol.appendSymbolLayer(QgsSimpleMarkerSymbolLayer())  # Compatible second
        renderer = QgsSingleSymbolRenderer(symbol)
        layer.setRenderer(renderer)

        is_compatible, reason = VectorLayerChecker.check(layer)

        self.assertTrue(is_compatible)
        self.assertEqual(reason, "")

    def test_mixed_symbol_layers(self):
        """Test layer with mixed symbol layers - should be compatible if one simple exists"""
        layer = self.create_qgishub_layer(QgsWkbTypes.PointGeometry)

        # Create symbol with mixed layers (simple + non-simple)
        symbol = QgsMarkerSymbol()
        symbol.deleteSymbolLayer(0)  # Remove default layer
        symbol.appendSymbolLayer(QgsSimpleMarkerSymbolLayer())  # Compatible first
        svg_layer = QgsSvgMarkerSymbolLayer("circle.svg")  # Incompatible second
        symbol.appendSymbolLayer(svg_layer)
        renderer = QgsSingleSymbolRenderer(symbol)
        layer.setRenderer(renderer)

        is_compatible, reason = VectorLayerChecker.check(layer)

        self.assertTrue(is_compatible)
        self.assertEqual(reason, "")

    def test_all_non_simple_symbol_layers(self):
        """Test layer with all non-simple symbol layers - should be incompatible"""
        layer = self.create_qgishub_layer(QgsWkbTypes.PointGeometry)

        # Create symbol with only non-simple layers
        symbol = QgsMarkerSymbol()
        symbol.deleteSymbolLayer(0)  # Remove default layer
        svg_layer1 = QgsSvgMarkerSymbolLayer("circle.svg")  # Incompatible first
        svg_layer2 = QgsSvgMarkerSymbolLayer("square.svg")  # Incompatible second
        symbol.appendSymbolLayer(svg_layer1)
        symbol.appendSymbolLayer(svg_layer2)
        renderer = QgsSingleSymbolRenderer(symbol)
        layer.setRenderer(renderer)

        is_compatible, reason = VectorLayerChecker.check(layer)

        self.assertFalse(is_compatible)
        self.assertEqual(reason, " - unsupported point renderer")

    def test_layer_validation_with_qgis_testing(self):
        """Test layer validation using QgisTestCase methods"""
        # Create layers for each geometry type
        point_layer = self.create_memory_layer(QgsWkbTypes.PointGeometry)
        line_layer = self.create_memory_layer(QgsWkbTypes.LineGeometry)
        polygon_layer = self.create_memory_layer(QgsWkbTypes.PolygonGeometry)

        # Use QgisTestCase assertion methods to validate layers
        self.assertIsNotNone(point_layer)
        self.assertIsNotNone(line_layer)
        self.assertIsNotNone(polygon_layer)

        # Verify geometry types are correct
        self.assertEqual(point_layer.geometryType(), QgsWkbTypes.PointGeometry)
        self.assertEqual(line_layer.geometryType(), QgsWkbTypes.LineGeometry)
        self.assertEqual(polygon_layer.geometryType(), QgsWkbTypes.PolygonGeometry)


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

        is_compatible, reason = RasterLayerChecker.check(layer)

        self.assertFalse(is_compatible)
        self.assertEqual(reason, " - raster provider not supported")

    def test_wms_xyz_type(self):
        """Test WMS layer with XYZ type"""
        layer = self.create_wms_layer(
            "tilePixelRatio=1&amp;type=xyz&amp;url=https://tile.openstreetmap.org/%7Bz%7D/%7Bx%7D/%7By%7D.png&amp;zmax=19&amp;zmin=0"
        )

        is_compatible, reason = RasterLayerChecker.check(layer)

        self.assertTrue(is_compatible)
        self.assertEqual(reason, "")

    def test_wms_xyz_type_uppercase(self):
        """Test WMS layer with XYZ type in uppercase"""
        layer = self.create_wms_layer(
            "tilePixelRatio=1&amp;type=XYZ&amp;url=https://tile.openstreetmap.org/%7Bz%7D/%7Bx%7D/%7By%7D.png&amp;zmax=19&amp;zmin=0"
        )

        is_compatible, reason = RasterLayerChecker.check(layer)

        self.assertTrue(is_compatible)
        self.assertEqual(reason, "")

    def test_wms_non_xyz_type(self):
        """Test WMS layer without XYZ type"""
        layer = self.create_wms_layer("url=http://example.com&param=value")

        is_compatible, reason = RasterLayerChecker.check(layer)

        self.assertFalse(is_compatible)
        self.assertEqual(reason, " - only XYZ type WMS supported")

    def test_xyzvectortiles_provider(self):
        """Test that xyzvectortiles provider is not supported"""
        layer = self.create_xyzvectortiles_layer()

        is_compatible, reason = RasterLayerChecker.check(layer)

        self.assertFalse(is_compatible)
        self.assertEqual(reason, " - raster provider not supported")


if __name__ == "__main__":
    import unittest

    unittest.main()
