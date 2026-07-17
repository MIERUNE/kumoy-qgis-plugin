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


def _cog_band_interleave_supported() -> bool:
    """COG ドライバが INTERLEAVE 作成オプション(=GDAL 3.11+)に対応するか。

    convert_to_cog の内部判定と同じ。GDAL バージョンではなく能力で見る。
    """
    col = gdal.GetDriverByName("COG").GetMetadataItem("DMD_CREATIONOPTIONLIST") or ""
    return "INTERLEAVE" in col


# 単バンドの変換は古い GDAL でも通る（CI の docker=GDAL 3.10.3 でも検証できる）。
# 多バンドの成功パス（INTERLEAVE=BAND 格納）だけは GDAL 3.11+ が要るのでスキップ、
# その拒否挙動を別テストで検証する。
requires_gdal_311 = pytest.mark.skipif(
    not _cog_band_interleave_supported(),
    reason="multi-band COG requires GDAL 3.11+ (INTERLEAVE creation option)",
)
only_without_gdal_311 = pytest.mark.skipif(
    _cog_band_interleave_supported(),
    reason="exercises the GDAL < 3.11 multi-band rejection path",
)


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

    @requires_gdal_311
    def test_stores_band_interleaved(self, tmp_path):
        """対応 GDAL では多バンドが INTERLEAVE=BAND で格納される。"""
        src = str(tmp_path / "src.tif")
        dst = str(tmp_path / "out.tif")
        ds = gdal.GetDriverByName("GTiff").Create(src, 16, 16, 3, gdal.GDT_Byte)
        ds.SetGeoTransform([0, 1, 0, 16, 0, -1])
        for i in (1, 2, 3):
            ds.GetRasterBand(i).Fill(i * 10)
        ds.Close()

        self._fn()(src, dst)

        out = gdal.Open(dst)
        assert out.GetMetadataItem("INTERLEAVE", "IMAGE_STRUCTURE") == "BAND"
        out.Close()

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


@pytest.mark.usefixtures("qgis_plugin_path")
class TestSourceHasCrs:
    def _fn(self):
        from plugin_dir.processing.upload_raster.cog import source_has_crs

        return source_has_crs

    def test_true_when_crs_embedded(self, tmp_path):
        src = str(tmp_path / "src.tif")
        _make_geotiff(src, with_crs=True)
        assert self._fn()(src) is True

    def test_false_when_crs_missing(self, tmp_path):
        src = str(tmp_path / "src.tif")
        _make_geotiff(src, with_crs=False)
        assert self._fn()(src) is False

    def test_defers_error_for_unopenable_path(self, tmp_path):
        """開けないパスは True（=割り当てなし）でエラー報告を convert_to_cog に委ねる。"""
        assert self._fn()(str(tmp_path / "missing.tif")) is True


@only_without_gdal_311
@pytest.mark.usefixtures("qgis_plugin_path")
def test_multiband_errors_without_gdal_311(tmp_path):
    """GDAL 3.11 未満では、多バンドの変換を成果物を残さず拒否する。

    単バンドは古い GDAL でも通る（TestConvertToCog の各テストが担保）。
    """
    from plugin_dir.processing.upload_raster.cog import convert_to_cog

    src = str(tmp_path / "src.tif")
    dst = str(tmp_path / "out.tif")
    ds = gdal.GetDriverByName("GTiff").Create(src, 16, 16, 3, gdal.GDT_Byte)
    ds.SetGeoTransform([0, 1, 0, 16, 0, -1])
    for i in (1, 2, 3):
        ds.GetRasterBand(i).Fill(i * 10)
    ds.Close()

    with pytest.raises(Exception, match="GDAL 3.11"):
        convert_to_cog(src, dst)
    assert not os.path.exists(dst)
