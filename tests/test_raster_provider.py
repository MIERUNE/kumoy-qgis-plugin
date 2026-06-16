"""kumoy/provider raster のテスト

URI 解析と、内部 gdal プロバイダへの委譲（描画に必要な read 系が機能すること）を
検証する。ダウンロードは行わず、キャッシュ済みの GeoTIFF を指すよう差し替える。
"""

import pytest


def _make_geotiff(path: str):
    from osgeo import gdal, osr

    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, 64, 48, 3, gdal.GDT_Byte)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    ds.SetGeoTransform([10.0, 0.1, 0, 50.0, 0, -0.1])
    for b in range(1, 4):
        ds.GetRasterBand(b).Fill(b * 40)
    ds = None


@pytest.fixture(scope="module")
def registered_metadata(qgis_app):
    from qgis.core import QgsProviderRegistry

    from plugin_dir.kumoy.provider.raster_dataprovider_metadata import (
        KumoyRasterProviderMetadata,
    )

    # 同一キーの二重登録は False になるだけで無害（他テストとの実行順に依存しない）。
    QgsProviderRegistry.instance().registerProvider(KumoyRasterProviderMetadata())


@pytest.mark.usefixtures("qgis_plugin_path", "registered_metadata")
class TestParseUri:
    def _fn(self):
        from plugin_dir.kumoy.provider.raster_dataprovider import parse_uri

        return parse_uri

    def test_parses_all_parts(self):
        project_id, raster_id, raster_name = self._fn()(
            "project_id=p-1;raster_id=r-2;raster_name=dem;"
        )
        assert project_id == "p-1"
        assert raster_id == "r-2"
        assert raster_name == "dem"

    def test_raises_without_required(self):
        with pytest.raises(ValueError):
            self._fn()("raster_name=dem;")


@pytest.mark.usefixtures("qgis_plugin_path", "registered_metadata")
class TestRasterDataProvider:
    @pytest.fixture
    def tif(self, tmp_path, monkeypatch):
        from plugin_dir.kumoy.provider import raster_dataprovider as rp

        path = str(tmp_path / "r-2.tif")
        _make_geotiff(path)

        # ダウンロードを発生させず、キャッシュ済みファイルを指すよう差し替える。
        monkeypatch.setattr(rp.local_cache.raster, "is_cached", lambda rid: True)
        monkeypatch.setattr(rp.local_cache.raster, "get_cache_path", lambda rid: path)
        return path

    def test_layer_is_valid_and_renders(self, tif):
        from qgis.core import QgsRasterLayer

        from plugin_dir.kumoy import constants

        uri = "project_id=p-1;raster_id=r-2;raster_name=dem;"
        layer = QgsRasterLayer(uri, "dem", constants.RASTER_DATA_PROVIDER_KEY)

        assert layer.isValid()
        assert layer.crs().authid() == "EPSG:4326"
        assert layer.bandCount() == 3
        assert layer.width() == 64
        assert layer.height() == 48

        provider = layer.dataProvider()
        assert provider.raster_id == "r-2"

        block = provider.block(1, layer.extent(), layer.width(), layer.height())
        assert block is not None and block.isValid()
        assert block.value(0, 0) == 40.0

    def test_renders_through_map_job(self, tif):
        """描画パイプラインは QgsRasterPipe をコピーしプロバイダを clone する。

        この経路を block() 直叩きテストは通らない。ここで実際にマップジョブで
        描画し、ピクセルが出る（背景の白ではない）ことまで確認して以下を防ぐ:
        - clone が自分自身（Python サブクラス）を返すと、GC でオーバーライドが
          失われ block() が空ブロックにフォールバック → 真っ白で何も描画されない。
        - 所有権の扱いを誤ると "pure virtual method called" で segfault する。
        """
        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsMapRendererSequentialJob,
            QgsMapSettings,
            QgsRasterLayer,
        )
        from qgis.PyQt.QtCore import QSize

        from plugin_dir.kumoy import constants

        uri = "project_id=p-1;raster_id=r-2;raster_name=dem;"
        layer = QgsRasterLayer(uri, "dem", constants.RASTER_DATA_PROVIDER_KEY)
        assert layer.isValid()

        ms = QgsMapSettings()
        ms.setLayers([layer])
        ms.setExtent(layer.extent())
        ms.setOutputSize(QSize(128, 96))
        ms.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))

        job = QgsMapRendererSequentialJob(ms)
        job.start()
        job.waitForFinished()
        image = job.renderedImage()

        assert image.width() == 128
        assert image.height() == 96

        # 中央ピクセルがラスタの実値（band値 40/80/120）であること。
        # 各バンド一様値なのでコントラスト強調なし＝生値が出る。背景白(255,255,255)
        # のまま＝「描画されていない」を確実に弾く。
        px = image.pixel(64, 48)
        r, g, b = (px >> 16) & 0xFF, (px >> 8) & 0xFF, px & 0xFF
        assert (r, g, b) == (40, 80, 120)

    def test_download_branch_constructs_and_leaves_no_dialog(
        self, tmp_path, monkeypatch
    ):
        """未キャッシュ＝ダウンロード経路（進捗ダイアログ付き）の唯一のカバレッジ。

        他テストは is_cached=True でこの分岐を通らない。ここでは sync をモックして
        ダウンロード完了を模し、(1) その経路でも valid なプロバイダになること、
        (2) 構築後イベントを回しても可視の QProgressDialog が残らないことを確認する。

        注: 実機(macOS)で稀に起きる「100%のまま閉じない」は QProgressDialog の
        自動表示タイマーが close() 後に発火して再表示される競合が原因で、finally の
        reset() でタイマーを止めて対処している。この競合は headless では再現しない
        ため、本テストはダイアログ後始末の意図ドキュメント＋経路カバレッジに留まる。
        """
        from qgis.PyQt.QtWidgets import QApplication, QProgressDialog

        from plugin_dir.kumoy import constants
        from plugin_dir.kumoy.provider import raster_dataprovider as rp

        path = str(tmp_path / "r-dl.tif")
        _make_geotiff(path)

        monkeypatch.setattr(rp.local_cache.raster, "is_cached", lambda rid: False)
        monkeypatch.setattr(rp.local_cache.raster, "get_cache_path", lambda rid: path)

        def fake_sync(raster_id, progress_callback=None, is_canceled=None):
            # 実ダウンロードの進捗更新を模して自動表示タイマーを arm させる。
            if progress_callback:
                progress_callback(0)
                progress_callback(100)
            return path

        monkeypatch.setattr(rp.local_cache.raster, "sync_local_cache", fake_sync)

        uri = "project_id=p-1;raster_id=r-dl;raster_name=dem;"
        provider = rp.KumoyRasterDataProvider(uri)
        assert provider.isValid()

        # queue された自動表示タイマーを発火させる。
        for _ in range(3):
            QApplication.processEvents()

        visible = [
            w
            for w in QApplication.topLevelWidgets()
            if isinstance(w, QProgressDialog) and w.isVisible()
        ]
        assert visible == []
