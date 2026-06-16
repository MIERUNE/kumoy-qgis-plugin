"""convert_to_cog のユニットテスト（GDAL が必要）"""

import pytest
from osgeo import gdal, osr


def _make_geotiff(path: str, with_crs: bool = True, size: int = 16) -> None:
    """テスト用 GeoTIFF を作る。"""
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(path, size, size, 1, gdal.GDT_Byte)
    ds.SetGeoTransform([0, 1, 0, size, 0, -1])
    if with_crs:
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.Fill(42)
    ds.FlushCache()
    ds = None


def _is_cog(path: str) -> bool:
    ds = gdal.Open(path)
    layout = ds.GetMetadataItem("LAYOUT", "IMAGE_STRUCTURE")
    ds = None
    return layout == "COG"


@pytest.mark.usefixtures("qgis_plugin_path")
class TestConvertToCog:
    def _fn(self):
        from plugin_dir.processing.upload_raster.cog import convert_to_cog

        return convert_to_cog

    def test_produces_cog(self, tmp_path):
        src = str(tmp_path / "src.tif")
        dst = str(tmp_path / "out.tif")
        _make_geotiff(src, with_crs=True)

        self._fn()(src, dst)

        assert _is_cog(dst)

    def test_preserves_crs(self, tmp_path):
        src = str(tmp_path / "src.tif")
        dst = str(tmp_path / "out.tif")
        _make_geotiff(src, with_crs=True)

        self._fn()(src, dst)

        ds = gdal.Open(dst)
        srs = osr.SpatialReference(wkt=ds.GetProjection())
        assert srs.GetAuthorityCode(None) == "4326"
        ds = None

    def test_does_not_reproject(self, tmp_path):
        """元データの geotransform/ピクセル値がそのまま保持されること。"""
        src = str(tmp_path / "src.tif")
        dst = str(tmp_path / "out.tif")
        _make_geotiff(src, with_crs=True)

        self._fn()(src, dst)

        ds = gdal.Open(dst)
        assert ds.GetGeoTransform()[0] == 0
        assert ds.GetRasterBand(1).ReadAsArray()[0][0] == 42
        ds = None

    def test_assigns_crs_when_missing(self, tmp_path):
        src = str(tmp_path / "src.tif")
        dst = str(tmp_path / "out.tif")
        _make_geotiff(src, with_crs=False)

        srs = osr.SpatialReference()
        srs.ImportFromEPSG(3857)
        self._fn()(src, dst, assign_crs_wkt=srs.ExportToWkt())

        ds = gdal.Open(dst)
        out_srs = osr.SpatialReference(wkt=ds.GetProjection())
        assert out_srs.GetAuthorityCode(None) == "3857"
        ds = None

    def test_cancellation_raises(self, tmp_path):
        from plugin_dir.processing.upload_raster.cog import CogConversionCanceled

        src = str(tmp_path / "src.tif")
        dst = str(tmp_path / "out.tif")
        # 進捗コールバックが複数回呼ばれるよう、ある程度の大きさにする。
        _make_geotiff(src, with_crs=True, size=2048)

        with pytest.raises(CogConversionCanceled):
            self._fn()(src, dst, is_canceled=lambda: True)

    def test_reports_progress(self, tmp_path):
        src = str(tmp_path / "src.tif")
        dst = str(tmp_path / "out.tif")
        _make_geotiff(src, with_crs=True)

        seen = []
        self._fn()(src, dst, progress_callback=seen.append)

        assert seen, "progress callback was never called"
        assert all(0 <= p <= 100 for p in seen)
