"""_resolve_assign_crs_wkt のユニットテスト（QGIS + GDAL が必要）。

「割り当て CRS の判定はレイヤ CRS ではなくファイルに焼き込まれた CRS で行う」
という契約を検証する。特に、CRS 無しファイルに QGIS 上で手動 CRS を設定した
ケースでその CRS が COG へ伝播すること（過去に黙って失われていた）を担保する。
"""

import pytest
from osgeo import gdal, osr
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsProcessingException,
    QgsRasterLayer,
)


def _make_geotiff(path: str, with_crs: bool) -> None:
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(path, 16, 16, 1, gdal.GDT_Byte)
    ds.SetGeoTransform([0, 1, 0, 16, 0, -1])
    if with_crs:
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).Fill(42)
    ds.FlushCache()
    ds.Close()


def _load_layer(path: str) -> QgsRasterLayer:
    layer = QgsRasterLayer(path, "test", "gdal")
    assert layer.isValid()
    return layer


@pytest.mark.usefixtures("qgis_plugin_path")
class TestResolveAssignCrsWkt:
    def _fn(self):
        from plugin_dir.processing.upload_raster.algorithm import (
            _resolve_assign_crs_wkt,
        )

        return _resolve_assign_crs_wkt

    def test_keeps_embedded_crs(self, tmp_path):
        """ファイルに CRS があれば何も割り当てない（再割り当てで壊さない）。"""
        src = str(tmp_path / "src.tif")
        _make_geotiff(src, with_crs=True)
        layer = _load_layer(src)

        assert self._fn()(layer) is None

    def test_uses_manually_set_layer_crs(self, tmp_path):
        """CRS 無しファイル + QGIS 上の手動設定 → その CRS を割り当てる。"""
        src = str(tmp_path / "src.tif")
        _make_geotiff(src, with_crs=False)
        layer = _load_layer(src)
        layer.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))

        wkt = self._fn()(layer)
        assert wkt is not None
        assert QgsCoordinateReferenceSystem.fromWkt(wkt).authid() == "EPSG:3857"

    def test_raises_when_no_crs_anywhere(self, tmp_path):
        src = str(tmp_path / "src.tif")
        _make_geotiff(src, with_crs=False)
        layer = _load_layer(src)
        layer.setCrs(QgsCoordinateReferenceSystem())

        with pytest.raises(QgsProcessingException):
            self._fn()(layer)
