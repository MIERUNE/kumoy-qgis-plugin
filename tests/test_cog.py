"""processing/raster/upload/cog.py (needs GDAL)."""

import os

import pytest
from osgeo import gdal, osr


def _make_geotiff(
    path: str, with_crs: bool = True, size: int = 16, georeferenced: bool = True
) -> None:
    ds = gdal.GetDriverByName("GTiff").Create(path, size, size, 1, gdal.GDT_Byte)
    if georeferenced:
        ds.SetGeoTransform([0, 1, 0, size, 0, -1])
    if with_crs:
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).Fill(42)
    ds.Close()


def _make_multiband(path: str) -> None:
    ds = gdal.GetDriverByName("GTiff").Create(path, 16, 16, 3, gdal.GDT_Byte)
    ds.SetGeoTransform([0, 1, 0, 16, 0, -1])
    for i in (1, 2, 3):
        ds.GetRasterBand(i).Fill(i * 10)
    ds.Close()


def _epsg(path: str) -> str:
    ds = gdal.Open(path)
    return osr.SpatialReference(wkt=ds.GetProjection()).GetAuthorityCode(None)


def _cog_band_interleave_supported() -> bool:
    options = gdal.GetDriverByName("COG").GetMetadataItem("DMD_CREATIONOPTIONLIST")
    return "INTERLEAVE" in (options or "")


# Single-band conversion works on any GDAL; only the multi-band success path
# needs 3.11+, and the refusal on older GDAL has its own test
requires_gdal_311 = pytest.mark.skipif(
    not _cog_band_interleave_supported(),
    reason="multi-band COG requires GDAL 3.11+ (INTERLEAVE creation option)",
)
only_without_gdal_311 = pytest.mark.skipif(
    _cog_band_interleave_supported(),
    reason="exercises the GDAL < 3.11 multi-band rejection path",
)


@pytest.fixture
def paths(qgis_plugin_path, tmp_path):
    return str(tmp_path / "src.tif"), str(tmp_path / "out.tif")


def convert(*args, **kwargs):
    from plugin_dir.processing.raster.upload.cog import convert_to_cog

    convert_to_cog(*args, **kwargs)


class TestConvertToCog:
    def test_produces_cog_without_altering_data(self, paths):
        src, dst = paths
        _make_geotiff(src)

        convert(src, dst)

        ds = gdal.Open(dst)
        assert ds.GetMetadataItem("LAYOUT", "IMAGE_STRUCTURE") == "COG"
        assert ds.GetGeoTransform() == (0, 1, 0, 16, 0, -1)
        assert ds.GetRasterBand(1).ReadAsArray()[0][0] == 42
        assert _epsg(dst) == "4326"

    def test_writes_approximate_statistics(self, paths):
        src, dst = paths
        _make_geotiff(src)

        convert(src, dst)

        # The STATISTICS_APPROXIMATE flag is never written by the COG path of
        # gdal_translate (3.8 to 3.14); the contract is that stats exist
        ds = gdal.Open(dst)  # keep: a band outlives no dataset
        metadata = ds.GetRasterBand(1).GetMetadata()
        assert float(metadata["STATISTICS_MINIMUM"]) == 42.0
        assert float(metadata["STATISTICS_MAXIMUM"]) == 42.0

    @requires_gdal_311
    def test_stores_band_interleaved(self, paths):
        src, dst = paths
        _make_multiband(src)

        convert(src, dst)

        ds = gdal.Open(dst)
        assert ds.GetMetadataItem("INTERLEAVE", "IMAGE_STRUCTURE") == "BAND"

    def test_assigns_crs_when_missing(self, paths):
        src, dst = paths
        _make_geotiff(src, with_crs=False)
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(3857)

        convert(src, dst, assign_crs_wkt=srs.ExportToWkt())

        assert _epsg(dst) == "3857"

    def test_assigned_crs_overrides_embedded(self, paths):
        # For a CRS overridden on the layer in QGIS; no reprojection
        src, dst = paths
        _make_geotiff(src)
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(3857)

        convert(src, dst, assign_crs_wkt=srs.ExportToWkt())

        assert _epsg(dst) == "3857"
        assert gdal.Open(dst).GetGeoTransform() == (0, 1, 0, 16, 0, -1)

    def test_georeferences_raster_without_geotransform(self, paths):
        src, dst = paths
        _make_geotiff(src, with_crs=False, georeferenced=False)

        convert(src, dst)

        assert gdal.Open(dst).GetGeoTransform(can_return_null=True) == (
            0,
            1,
            0,
            0,
            0,
            -1,
        )
        # The user's file is left alone (no sidecar written next to it)
        assert not os.path.exists(src + ".aux.xml")

    def test_cancel_raises_a_task_cancel(self, paths):
        from plugin_dir.kumoy.tasks import Canceled
        from plugin_dir.processing.raster.upload.cog import CogConversionCanceled

        src, dst = paths
        _make_geotiff(src, size=2048)  # big enough for several progress calls

        with pytest.raises(CogConversionCanceled):
            convert(src, dst, is_canceled=lambda: True)
        assert issubclass(CogConversionCanceled, Canceled)  # silent in run_task

    def test_reports_progress(self, paths):
        src, dst = paths
        _make_geotiff(src)
        seen = []

        convert(src, dst, progress_callback=seen.append)

        assert seen and all(0 <= p <= 100 for p in seen)

    def test_unreadable_source_raises(self, paths):
        src, dst = paths
        with pytest.raises(Exception, match="failed to open"):
            convert(src, dst)

    @only_without_gdal_311
    def test_multiband_refused_without_gdal_311(self, paths):
        src, dst = paths
        _make_multiband(src)

        with pytest.raises(Exception, match="GDAL 3.11"):
            convert(src, dst)
        assert not os.path.exists(dst)


class TestReadSourceCrsWkt:
    def _fn(self):
        from plugin_dir.processing.raster.upload.cog import read_source_crs_wkt

        return read_source_crs_wkt

    def test_returns_embedded_crs(self, paths):
        src, _ = paths
        _make_geotiff(src)
        wkt = self._fn()(src)
        assert osr.SpatialReference(wkt=wkt).GetAuthorityCode(None) == "4326"

    def test_returns_none_without_crs(self, paths):
        src, _ = paths
        _make_geotiff(src, with_crs=False)
        assert self._fn()(src) is None

    def test_defers_error_for_unopenable_path(self, paths):
        from plugin_dir.processing.raster.upload.cog import SOURCE_UNREADABLE

        src, _ = paths
        assert self._fn()(src) is SOURCE_UNREADABLE

    def test_works_in_gdal_exception_mode(self, paths):
        # Other plugins may turn exceptions on process-wide
        src, _ = paths
        previous = gdal.GetUseExceptions()
        gdal.UseExceptions()
        try:
            from plugin_dir.processing.raster.upload.cog import SOURCE_UNREADABLE

            assert self._fn()(src) is SOURCE_UNREADABLE
            with pytest.raises(Exception, match="failed to open"):
                convert(src, src + ".out")
        finally:
            if not previous:
                gdal.DontUseExceptions()
