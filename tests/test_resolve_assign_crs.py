"""_resolve_assign_crs_wkt のユニットテスト（QGIS + GDAL が必要）。

「ユーザーが QGIS 上で見ている CRS がそのままアップロードされる」という契約を
検証する。特に、CRS 無しファイルに QGIS 上で手動 CRS を設定したケースでその
CRS が COG へ伝播すること（過去に黙って失われていた）と、ファイルの CRS を
QGIS 上で別の CRS に上書きしたケースで上書きが勝つことを担保する。
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
        """ファイルの CRS とレイヤ CRS が一致していれば何も割り当てない。"""
        src = str(tmp_path / "src.tif")
        _make_geotiff(src, with_crs=True)
        layer = _load_layer(src)

        assert self._fn()(layer, QgsCoordinateReferenceSystem()) is None

    def test_layer_override_wins_over_embedded_crs(self, tmp_path):
        """ファイルに CRS があっても、QGIS 上の手動上書きが勝つ。"""
        src = str(tmp_path / "src.tif")
        _make_geotiff(src, with_crs=True)  # EPSG:4326 埋め込み
        layer = _load_layer(src)
        layer.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))

        wkt = self._fn()(layer, QgsCoordinateReferenceSystem())
        assert wkt is not None
        assert QgsCoordinateReferenceSystem.fromWkt(wkt).authid() == "EPSG:3857"

    def test_uses_manually_set_layer_crs(self, tmp_path):
        """CRS 無しファイル + QGIS 上の手動設定 → その CRS を割り当てる。"""
        src = str(tmp_path / "src.tif")
        _make_geotiff(src, with_crs=False)
        layer = _load_layer(src)
        layer.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))

        wkt = self._fn()(layer, QgsCoordinateReferenceSystem())
        assert wkt is not None
        assert QgsCoordinateReferenceSystem.fromWkt(wkt).authid() == "EPSG:3857"

    def test_assign_crs_param_takes_precedence(self, tmp_path):
        """このアルゴリズム実行への明示指定はレイヤ CRS より優先される。"""
        src = str(tmp_path / "src.tif")
        _make_geotiff(src, with_crs=False)
        layer = _load_layer(src)
        layer.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))

        wkt = self._fn()(layer, QgsCoordinateReferenceSystem("EPSG:6668"))
        assert QgsCoordinateReferenceSystem.fromWkt(wkt).authid() == "EPSG:6668"

    def test_raises_when_no_crs_anywhere(self, tmp_path):
        src = str(tmp_path / "src.tif")
        _make_geotiff(src, with_crs=False)
        layer = _load_layer(src)
        layer.setCrs(QgsCoordinateReferenceSystem())

        with pytest.raises(QgsProcessingException):
            self._fn()(layer, QgsCoordinateReferenceSystem())
