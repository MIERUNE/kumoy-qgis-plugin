"""Map保存時に <extent> が書き込まれることのテスト

QgsVectorLayer はプロバイダの extent を一度だけ問い合わせてキャッシュし、
QgsProject.write() はそのキャッシュ値を書き出す（null なら <extent> 要素そのものが
欠落する）。Kumoyレイヤーは「サーバ側にまだextentが無い」瞬間に null を返しうるので、
シリアライズ直前に再計算させる必要がある。
"""

import re
import types

import pytest


def _extent_block(qgs_str: str, layer_name: str):
    """Return the <extent> block of the named maplayer, or None if absent."""
    for m in re.finditer(r"<maplayer.*?</maplayer>", qgs_str, re.S):
        block = m.group(0)
        name = re.search(r"<layername>(.*?)</layername>", block)
        if name is None or name.group(1) != layer_name:
            continue
        extent = re.search(r"<extent>.*?</extent>", block, re.S)
        return extent.group(0) if extent else None
    raise AssertionError(f"maplayer '{layer_name}' not found in project")


@pytest.mark.usefixtures("qgis_plugin_path")
class TestFeatureCountFallback:
    """ローカルキャッシュが無いときはサーバ側のcountを返す。

    0 を返すと QgsVectorLayer.extent() が再計算をスキップして null のままになる。
    """

    def _provider(self, kumoy_vector, cached_layer):
        from qgis.core import QgsVectorDataProvider

        from plugin_dir.kumoy.provider.dataprovider import KumoyDataProvider

        class _Provider(KumoyDataProvider):
            def __init__(self):
                # KumoyDataProvider.__init__ はAPI通信・キャッシュ同期を伴うので飛ばす
                QgsVectorDataProvider.__init__(self, "")
                self.kumoy_vector = kumoy_vector
                self.cached_layer = cached_layer

        return _Provider()

    def test_falls_back_to_server_count_without_cache(self, qgis_app):
        provider = self._provider(types.SimpleNamespace(count=7), None)
        assert provider.featureCount() == 7

    def test_zero_without_cache_and_metadata(self, qgis_app):
        provider = self._provider(None, None)
        assert provider.featureCount() == 0

    def test_cached_layer_takes_precedence(self, qgis_app):
        """キャッシュがあればそれが真。空なら 7 ではなく 0 を返す。"""
        from qgis.core import QgsVectorLayer

        cached = QgsVectorLayer("Point?crs=EPSG:4326", "cache", "memory")
        provider = self._provider(types.SimpleNamespace(count=7), cached)
        assert provider.featureCount() == 0


@pytest.fixture(scope="session")
def _registered_fake_provider(qgis_app):
    """Register a stub provider under the Kumoy vector provider key.

    Mimics KumoyDataProvider: the extent comes from server metadata (null while
    the server has none) and the feature count from the local cache. Provider
    metadata can only be registered once per QGIS session, so the stub reads its
    mutable state from the returned object.
    """
    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsDataProvider,
        QgsFeatureRequest,
        QgsField,
        QgsFields,
        QgsProviderMetadata,
        QgsProviderRegistry,
        QgsRectangle,
        QgsVectorDataProvider,
        QgsVectorLayer,
        QgsWkbTypes,
    )
    from qgis.PyQt.QtCore import QVariant

    from plugin_dir.kumoy.constants import DATA_PROVIDER_KEY

    state = types.SimpleNamespace(extent=QgsRectangle(), feature_count=0)

    class _FakeProvider(QgsVectorDataProvider):
        @classmethod
        def createProvider(cls, uri, options, flags=QgsDataProvider.ReadFlags()):
            return _FakeProvider(uri)

        def name(self):
            return DATA_PROVIDER_KEY

        def isValid(self):
            return True

        def crs(self):
            return QgsCoordinateReferenceSystem("EPSG:4326")

        def wkbType(self):
            return QgsWkbTypes.Point

        def geometryType(self):
            return QgsWkbTypes.Point

        def fields(self):
            fields = QgsFields()
            fields.append(QgsField("kumoy_id", QVariant.LongLong))
            return fields

        def extent(self):
            return state.extent

        def featureCount(self):
            return state.feature_count

        def getFeatures(self, request=QgsFeatureRequest()):
            empty = QgsVectorLayer("Point?crs=EPSG:4326", "empty", "memory")
            return empty.getFeatures(request)

        def capabilities(self):
            return QgsVectorDataProvider.Capabilities()

    # 同一キーの二重登録は False になるだけで無害
    QgsProviderRegistry.instance().registerProvider(
        QgsProviderMetadata(
            DATA_PROVIDER_KEY, "fake kumoy provider", _FakeProvider.createProvider
        )
    )
    return state


@pytest.fixture
def fake_kumoy_provider(_registered_fake_provider):
    """Reset the stub provider's state for each test."""
    from qgis.core import QgsRectangle

    _registered_fake_provider.extent = QgsRectangle()
    _registered_fake_provider.feature_count = 0
    return _registered_fake_provider


def _make_tif(path: str):
    from osgeo import gdal, osr

    ds = gdal.GetDriverByName("GTiff").Create(path, 8, 8, 1, gdal.GDT_Byte)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    ds.SetGeoTransform([10.0, 0.1, 0, 50.0, 0, -0.1])
    ds.Close()


@pytest.fixture(scope="session")
def _registered_raster_metadata(qgis_app):
    from qgis.core import QgsProviderRegistry

    from plugin_dir.kumoy.provider.raster_dataprovider_metadata import (
        KumoyRasterProviderMetadata,
    )

    # 同一キーの二重登録は False になるだけで無害
    QgsProviderRegistry.instance().registerProvider(KumoyRasterProviderMetadata())


@pytest.mark.usefixtures("qgis_plugin_path")
class TestSerializeProjectExtent:
    @pytest.fixture
    def kumoy_raster_layer(
        self, _registered_raster_metadata, monkeypatch, tmp_path, kumoy_layer
    ):
        """Kumoyラスタレイヤーをプロジェクトに追加する（kumoy_layer の後に追加）。"""
        from qgis.core import QgsProject, QgsRasterLayer

        from plugin_dir.kumoy import constants
        from plugin_dir.kumoy.provider import raster_dataprovider as rp

        path = str(tmp_path / "r-1.tif")
        _make_tif(path)
        monkeypatch.setattr(rp.local_cache.raster, "is_cached", lambda rid: True)
        monkeypatch.setattr(rp.local_cache.raster, "get_cache_path", lambda rid: path)

        layer = QgsRasterLayer(
            "project_id=p-1;raster_id=r-1;raster_name=dem;",
            "dem",
            constants.RASTER_DATA_PROVIDER_KEY,
        )
        assert layer.isValid()
        assert layer.dataProvider().name() == constants.RASTER_DATA_PROVIDER_KEY
        QgsProject.instance().addMapLayer(layer)
        return layer

    @pytest.fixture
    def kumoy_layer(self, fake_kumoy_provider):
        from qgis.core import QgsProject, QgsVectorLayer

        from plugin_dir.kumoy.constants import DATA_PROVIDER_KEY

        project = QgsProject.instance()
        project.clear()
        layer = QgsVectorLayer(
            "project_id=p-1;vector_id=v-1;vector_name=points;vector_type=POINT;",
            "points",
            DATA_PROVIDER_KEY,
        )
        assert layer.isValid()
        project.addMapLayer(layer)
        yield layer
        project.clear()

    def test_extent_written(self, kumoy_layer, fake_kumoy_provider):
        from qgis.core import QgsRectangle

        from plugin_dir.kumoy.local_cache.map import serialize_project

        fake_kumoy_provider.extent = QgsRectangle(139.0, 35.0, 140.0, 36.0)
        fake_kumoy_provider.feature_count = 3

        block = _extent_block(serialize_project(), "points")
        assert block is not None
        assert "<xmin>139</xmin>" in block

    def test_extent_recovered_after_null_was_cached(
        self, kumoy_layer, fake_kumoy_provider
    ):
        """空のVectorに地物を追加したあと保存するケース。

        レイヤー追加直後の描画で null がキャッシュされても、保存時には
        サーバ側の extent が書き込まれること。
        """
        from qgis.core import QgsRectangle

        from plugin_dir.kumoy.local_cache.map import serialize_project

        assert kumoy_layer.extent().isNull()  # ここで null がキャッシュされる

        fake_kumoy_provider.extent = QgsRectangle(139.0, 35.0, 140.0, 36.0)
        fake_kumoy_provider.feature_count = 3

        block = _extent_block(serialize_project(), "points")
        assert block is not None
        assert "<xmin>139</xmin>" in block

    def test_kumoy_raster_layer_does_not_break_serialization(
        self, kumoy_layer, fake_kumoy_provider, kumoy_raster_layer
    ):
        """QgsRasterLayer に updateExtents() は無いので、触ってはいけない。"""
        from qgis.core import QgsRectangle

        from plugin_dir.kumoy.local_cache.map import serialize_project

        fake_kumoy_provider.extent = QgsRectangle(139.0, 35.0, 140.0, 36.0)
        fake_kumoy_provider.feature_count = 3

        qgs_str = serialize_project()

        block = _extent_block(qgs_str, "points")
        assert block is not None
        assert "<xmin>139</xmin>" in block
        assert _extent_block(qgs_str, "dem") is not None

    def test_stale_extent_updated(self, kumoy_layer, fake_kumoy_provider):
        from qgis.core import QgsRectangle

        from plugin_dir.kumoy.local_cache.map import serialize_project

        fake_kumoy_provider.extent = QgsRectangle(0.0, 0.0, 1.0, 1.0)
        fake_kumoy_provider.feature_count = 1
        assert not kumoy_layer.extent().isNull()

        fake_kumoy_provider.extent = QgsRectangle(139.0, 35.0, 140.0, 36.0)

        block = _extent_block(serialize_project(), "points")
        assert block is not None
        assert "<xmin>139</xmin>" in block
