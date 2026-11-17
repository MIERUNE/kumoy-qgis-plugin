"""processing/raster/upload/materialize.py (needs QGIS and GDAL)."""

import gc
import os

import pytest
from osgeo import gdal, osr
from qgis.core import QgsRasterLayer
from qgis.PyQt.QtCore import QUrlQuery


def _make_geotiff(path: str, fill: int = 21) -> None:
    ds = gdal.GetDriverByName("GTiff").Create(path, 8, 8, 1, gdal.GDT_Byte)
    ds.SetGeoTransform([0, 1, 0, 8, 0, -1])
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).Fill(fill)
    ds.FlushCache()
    ds.Close()


def _virtualraster_layer(base_tif: str, formula: str) -> QgsRasterLayer:
    """A QGIS virtual raster (provider virtualraster) reading base_tif.

    Not added to the project: a virtualraster layer left in QgsProject makes
    QGIS segfault on teardown.
    """
    q = QUrlQuery()
    for key, value in [
        ("crs", "EPSG:4326"),
        ("extent", "0,0,8,8"),
        ("width", "8"),
        ("height", "8"),
        ("formula", formula),
        ("band1:uri", base_tif),
        ("band1:provider", "gdal"),
    ]:
        q.addQueryItem(key, value)
    return QgsRasterLayer("?" + q.toString(), "virt", "virtualraster")


@pytest.mark.usefixtures("qgis_plugin_path")
class TestMaterializeToGeotiff:
    def _fn(self):
        from plugin_dir.processing.raster.upload.materialize import (
            materialize_to_geotiff,
        )

        return materialize_to_geotiff

    def test_virtualraster_materialized(self, tmp_path):
        """The virtual raster becomes a GeoTIFF that gdal.Open reads."""
        base = str(tmp_path / "base.tif")
        dst = str(tmp_path / "out.tif")
        _make_geotiff(base, fill=21)
        layer = _virtualraster_layer(base, "band1@1 * 2")
        assert layer.isValid()

        try:
            self._fn()(layer, dst)

            ds = gdal.Open(dst)
            assert ds is not None
            assert (ds.RasterXSize, ds.RasterYSize) == (8, 8)
            # The formula band1@1 * 2 applies: 21 -> 42 (no reprojection)
            assert ds.GetRasterBand(1).ReadAsArray()[0][0] == 42
            srs = osr.SpatialReference(wkt=ds.GetProjection())
            assert srs.GetAuthorityCode(None) == "4326"
            ds.Close()
        finally:
            del layer
            gc.collect()

    def test_unsupported_provider_rejected(self, tmp_path):
        """Other providers (WMS, ...) are refused with a clear error."""
        # Even an invalid WMS layer reports providerType() 'wms'
        layer = QgsRasterLayer("crs=EPSG:3857&url=http://example.com/wms", "wms", "wms")
        assert layer.providerType() == "wms"

        with pytest.raises(Exception, match="unsupported source type"):
            self._fn()(layer, str(tmp_path / "out.tif"))

    def test_cancellation_raises(self, tmp_path):
        """Canceled up front: raises a task cancel and writes nothing."""
        from plugin_dir.kumoy.tasks import Canceled
        from plugin_dir.processing.raster.upload.materialize import (
            RasterMaterializeCanceled,
        )

        base = str(tmp_path / "base.tif")
        dst = str(tmp_path / "out.tif")
        _make_geotiff(base)
        layer = _virtualraster_layer(base, "band1@1")

        # No `as info`: its traceback would keep the virtual raster alive
        # past QGIS's teardown (segfault)
        with pytest.raises(RasterMaterializeCanceled):
            self._fn()(layer, dst, is_canceled=lambda: True)
        assert issubclass(RasterMaterializeCanceled, Canceled)

        assert not os.path.exists(dst)
        del layer
        gc.collect()
