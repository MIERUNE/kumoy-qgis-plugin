"""convert_to_cog のユニットテスト（GDAL が必要）"""

import os

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
    ds.Close()


def _is_cog(path: str) -> bool:
    ds = gdal.Open(path)
    layout = ds.GetMetadataItem("LAYOUT", "IMAGE_STRUCTURE")
    ds.Close()
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
        ds.Close()

    def test_does_not_reproject(self, tmp_path):
        """元データの geotransform/ピクセル値がそのまま保持されること。"""
        src = str(tmp_path / "src.tif")
        dst = str(tmp_path / "out.tif")
        _make_geotiff(src, with_crs=True)

        self._fn()(src, dst)

        ds = gdal.Open(dst)
        assert ds.GetGeoTransform()[0] == 0
        assert ds.GetRasterBand(1).ReadAsArray()[0][0] == 42
        ds.Close()

    def test_writes_approximate_statistics(self, tmp_path):
        src = str(tmp_path / "src.tif")
        dst = str(tmp_path / "out.tif")
        _make_geotiff(src, with_crs=True)

        self._fn()(src, dst)

        ds = gdal.Open(dst)
        metadata = ds.GetRasterBand(1).GetMetadata()
        # STATISTICS_APPROXIMATE フラグは検証しない。gdal_translate の COG 経路は
        # どの GDAL バージョン(3.8〜3.14 で確認)でもこのフラグを書き出さない。
        # 契約は「近似統計そのものが書かれること」で、それは min/max の存在で担保する。
        assert float(metadata["STATISTICS_MINIMUM"]) == 42.0
        assert float(metadata["STATISTICS_MAXIMUM"]) == 42.0
        ds.Close()

    def _make_multiband(self, path: str, bands: int) -> None:
        ds = gdal.GetDriverByName("GTiff").Create(path, 16, 16, bands, gdal.GDT_Byte)
        ds.SetGeoTransform([0, 1, 0, 16, 0, -1])
        for i in range(1, bands + 1):
            ds.GetRasterBand(i).Fill(i * 10)
        ds.Close()

    def test_many_bands_depend_on_band_interleave_support(self, tmp_path):
        """4 バンド超は、COG が BAND 格納に対応する GDAL でのみ変換を許す。

        非対応の GDAL では PIXEL 格納の遅い COG を作らせず例外を送出する。
        対応する GDAL では INTERLEAVE=BAND で格納される。
        """
        from plugin_dir.processing.upload_raster.cog import (
            _cog_supports_band_interleave,
        )

        src = str(tmp_path / "src.tif")
        dst = str(tmp_path / "out.tif")
        self._make_multiband(src, bands=4)

        if _cog_supports_band_interleave():
            self._fn()(src, dst)
            ds = gdal.Open(dst)
            assert ds.GetMetadataItem("INTERLEAVE", "IMAGE_STRUCTURE") == "BAND"
            ds.Close()
        else:
            with pytest.raises(Exception, match="GDAL 3.11"):
                self._fn()(src, dst)
            assert not os.path.exists(dst)

    def test_rgb_converts_even_without_band_interleave(self, tmp_path):
        """3 バンド(RGB)までは、BAND 格納非対応の GDAL でも PIXEL 格納で許容する。"""
        src = str(tmp_path / "src.tif")
        dst = str(tmp_path / "out.tif")
        self._make_multiband(src, bands=3)

        self._fn()(src, dst)

        assert _is_cog(dst)

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
        ds.Close()

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
