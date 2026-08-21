"""ui/layers/convert_raster のスタイルコピーのテスト

疑似カラーの classificationMin/Max が未設定(NaN)なレイヤーをコピーすると、
QGIS のスタイルXML往復がシェーダーの有効な min/max を NaN で上書きし、
変換後だけ凡例が「nan」表示になる。_copy_layer_style がこれを復元することを
検証する。
"""

import math

import pytest


def _make_gradient_tif(path: str):
    import struct

    from osgeo import gdal, osr

    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, 64, 48, 1, gdal.GDT_Float32)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    ds.SetGeoTransform([10.0, 0.1, 0, 50.0, 0, -0.1])
    band = ds.GetRasterBand(1)
    for y in range(48):
        row = [float(x + y) for x in range(64)]
        band.WriteRaster(0, y, 64, 1, struct.pack("f" * 64, *row))
    ds.Close()


def _set_pseudocolor(layer, with_classification: bool):
    """min=0/max=110 の Interpolated 疑似カラーを設定する。

    with_classification=False はシェーダー値のみ有効で classificationMin/Max が
    NaN のまま、というスタイル（古い .qml 由来やスクリプト設定で現実に起きる）。
    """
    from qgis.core import (
        QgsColorRampShader,
        QgsRasterShader,
        QgsSingleBandPseudoColorRenderer,
    )
    from qgis.PyQt.QtGui import QColor

    fcn = QgsColorRampShader()
    fcn.setColorRampType(QgsColorRampShader.Interpolated)
    fcn.setColorRampItemList(
        [
            QgsColorRampShader.ColorRampItem(0, QColor(0, 0, 255), "0"),
            QgsColorRampShader.ColorRampItem(110, QColor(255, 0, 0), "110"),
        ]
    )
    fcn.setMinimumValue(0.0)
    fcn.setMaximumValue(110.0)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(fcn)
    renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
    if with_classification:
        renderer.setClassificationMin(0.0)
        renderer.setClassificationMax(110.0)
    layer.setRenderer(renderer)


@pytest.fixture(scope="module")
def registered_metadata(qgis_app):
    from qgis.core import QgsProviderRegistry

    from plugin_dir.kumoy.provider.raster_dataprovider_metadata import (
        KumoyRasterProviderMetadata,
    )

    # 同一キーの二重登録は False になるだけで無害（他テストとの実行順に依存しない）。
    QgsProviderRegistry.instance().registerProvider(KumoyRasterProviderMetadata())


@pytest.mark.usefixtures("qgis_plugin_path", "registered_metadata")
@pytest.mark.parametrize("with_classification", [True, False])
def test_copy_pseudocolor_style_keeps_shader_minmax(
    tmp_path, monkeypatch, with_classification
):
    from qgis.core import QgsRasterLayer

    from plugin_dir.kumoy import constants
    from plugin_dir.kumoy.provider import raster_dataprovider as rp
    from plugin_dir.ui.layers.convert import _copy_layer_style

    path = str(tmp_path / "r-2.tif")
    _make_gradient_tif(path)
    monkeypatch.setattr(rp.local_cache.raster, "is_cached", lambda rid: True)
    monkeypatch.setattr(rp.local_cache.raster, "get_cache_path", lambda rid: path)

    source = QgsRasterLayer(path, "src", "gdal")
    assert source.isValid()
    _set_pseudocolor(source, with_classification)

    uri = "project_id=p-1;raster_id=r-2;raster_name=dem;"
    target = QgsRasterLayer(uri, "dem", constants.RASTER_DATA_PROVIDER_KEY)
    assert target.isValid()

    _copy_layer_style(source, target)

    # 凡例（QgsColorRampLegendNode）はシェーダーの min/max から作られる。
    shader_fn = target.renderer().shader().rasterShaderFunction()
    assert shader_fn.minimumValue() == 0.0
    assert shader_fn.maximumValue() == 110.0
    assert not math.isnan(target.renderer().classificationMin())
    assert not math.isnan(target.renderer().classificationMax())

    # 色分け項目（描画）は元のまま。
    items = shader_fn.colorRampItemList()
    assert [item.value for item in items] == [0, 110]
