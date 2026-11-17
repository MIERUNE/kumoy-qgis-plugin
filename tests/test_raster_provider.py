"""Kumoy raster provider, its placeholder and the reload after download.

Downloads are replaced by a recorder; "the download finished" is simulated by
writing the GeoTIFF into the (temporary) cache.
"""

import os

import pytest

URI = "project_id=p-1;raster_id=r-2;raster_name=dem;"


def _make_geotiff(path: str):
    from osgeo import gdal, osr

    ds = gdal.GetDriverByName("GTiff").Create(path, 64, 48, 3, gdal.GDT_Byte)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    ds.SetGeoTransform([10.0, 0.1, 0, 50.0, 0, -0.1])
    for b in range(1, 4):
        ds.GetRasterBand(b).Fill(b * 40)
    ds.Close()


def _render(layer):
    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsMapRendererSequentialJob,
        QgsMapSettings,
        QgsRectangle,
    )
    from qgis.PyQt.QtCore import QSize

    settings = QgsMapSettings()
    settings.setLayers([layer])
    settings.setExtent(QgsRectangle(10, 45.2, 16.4, 50))  # the test raster's
    settings.setOutputSize(QSize(128, 96))
    settings.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    job = QgsMapRendererSequentialJob(settings)
    job.start()
    job.waitForFinished()
    px = job.renderedImage().pixel(64, 48)
    return (px >> 16) & 0xFF, (px >> 8) & 0xFF, px & 0xFF


@pytest.fixture(scope="module")
def registered_metadata(qgis_app):
    from qgis.core import QgsProviderRegistry

    from plugin_dir.kumoy.provider.raster_dataprovider_metadata import (
        KumoyRasterProviderMetadata,
    )

    # Registering a key twice just returns False
    QgsProviderRegistry.instance().registerProvider(KumoyRasterProviderMetadata())


@pytest.fixture
def env(registered_metadata, tmp_path, monkeypatch):
    """Temporary cache, recorded fetches, and a clean project afterwards."""
    from types import SimpleNamespace

    from qgis.core import QgsProject

    from plugin_dir.kumoy import download
    from plugin_dir.kumoy.local_cache import raster

    cache_dir = tmp_path / "rasters"
    cache_dir.mkdir()
    monkeypatch.setattr(raster, "_get_cache_dir", lambda: str(cache_dir))
    fetches = []
    monkeypatch.setattr(
        download,
        "fetch_raster",
        lambda rid, name, on_ready=None: fetches.append((rid, name, on_ready)),
    )
    yield SimpleNamespace(
        fetches=fetches,
        tif=str(cache_dir / "r-2.tif"),
        project_file=str(tmp_path / "map.qgs"),
    )
    QgsProject.instance().clear()


def _layer(name="dem"):
    from qgis.core import QgsRasterLayer

    from plugin_dir.kumoy import constants

    return QgsRasterLayer(URI, name, constants.RASTER_DATA_PROVIDER_KEY)


class TestParseUri:
    def test_parses_all_parts(self, registered_metadata):
        from plugin_dir.kumoy.provider.raster_dataprovider import parse_uri

        assert parse_uri(URI) == ("p-1", "r-2", "dem")

    def test_requires_ids(self, registered_metadata):
        from plugin_dir.kumoy.provider.raster_dataprovider import parse_uri

        with pytest.raises(ValueError):
            parse_uri("raster_name=dem;")


class TestCached:
    def test_reads_the_cached_cog_without_network(self, env):
        _make_geotiff(env.tif)
        layer = _layer()

        assert layer.isValid()
        assert env.fetches == []
        assert layer.crs().authid() == "EPSG:4326"
        assert (layer.bandCount(), layer.width(), layer.height()) == (3, 64, 48)
        block = layer.dataProvider().block(1, layer.extent(), 64, 48)
        assert block.value(0, 0) == 40.0

    def test_renders_through_map_job(self, env):
        """The render pipeline clones the provider; a clone that loses the
        Python overrides renders blank (or crashes on a pure virtual)."""
        _make_geotiff(env.tif)
        assert _render(_layer()) == (40, 80, 120)


class TestPlaceholder:
    def test_uncached_layer_is_valid_empty_and_fetches(self, env):
        layer = _layer()

        assert layer.isValid()  # an invalid layer triggers QGIS's bad-layer dialog
        assert layer.extent().isNull()
        assert layer.dataProvider().xSize() == 0
        assert [f[:2] for f in env.fetches] == [("r-2", "dem")]

    def test_renders_nothing_without_crashing(self, env):
        layer = _layer()
        assert _render(layer) == (255, 255, 255)
        # Clones made by the renderer do not start more downloads
        assert len(env.fetches) == 1


class TestReload:
    def _save_project_with_styled_layer(self, env):
        from qgis.core import QgsProject, QgsRasterRange

        _make_geotiff(env.tif)
        layer = _layer()
        layer.renderer().setOpacity(0.5)
        layer.dataProvider().setUserNoDataValue(3, [QgsRasterRange(7, 7)])
        QgsProject.instance().addMapLayer(layer)
        assert QgsProject.instance().write(env.project_file)
        QgsProject.instance().clear()

    def test_project_layer_comes_alive_with_its_saved_style(self, env):
        from qgis.core import QgsProject

        from plugin_dir.ui.layers import raster as raster_layers

        self._save_project_with_styled_layer(env)
        os.rename(env.tif, env.tif + ".away")  # opened on a machine without cache

        assert QgsProject.instance().read(env.project_file)
        [layer] = QgsProject.instance().mapLayers().values()
        assert layer.isValid() and layer.extent().isNull()
        assert env.fetches

        os.rename(env.tif + ".away", env.tif)  # the download finished
        raster_layers.reload_layers("r-2")

        assert layer.width() == 64
        assert layer.renderer().type() == "multibandcolor"
        assert layer.renderer().opacity() == 0.5
        [nodata] = layer.dataProvider().userNoDataValues(3)
        assert (nodata.min(), nodata.max()) == (7, 7)
        assert _render(layer) != (255, 255, 255)

    def test_new_layer_gets_default_style_of_the_real_bands(self, env):
        from qgis.core import QgsProject

        from plugin_dir.ui.layers import raster as raster_layers

        layer = _layer()
        assert layer.renderer().type() == "singlebandgray"  # from the placeholder
        QgsProject.instance().addMapLayer(layer)

        _make_geotiff(env.tif)
        raster_layers.reload_layers("r-2")

        assert layer.renderer().type() == "multibandcolor"
        assert _render(layer) == (40, 80, 120)

    def test_skips_layers_already_reading_the_cog(self, env):
        from qgis.core import QgsProject

        from plugin_dir.ui.layers import raster as raster_layers

        _make_geotiff(env.tif)
        layer = _layer()
        QgsProject.instance().addMapLayer(layer)
        layer.renderer().setOpacity(0.25)  # an edit a reload would undo
        provider = layer.dataProvider()

        raster_layers.reload_layers("r-2")

        assert layer.dataProvider() is provider
        assert layer.renderer().opacity() == 0.25


class TestAddRasterToMap:
    def _raster(self):
        from plugin_dir.kumoy.api.models import Raster

        return Raster(id="r-2", name="dem", projectId="p-1")

    def test_adds_once_cached(self, env):
        from qgis.core import QgsProject

        from plugin_dir.ui.layers import raster as raster_layers

        raster_layers.add_raster_to_map(self._raster())
        [(rid, _name, on_ready)] = env.fetches
        assert rid == "r-2"
        assert QgsProject.instance().mapLayers() == {}

        _make_geotiff(env.tif)
        on_ready()

        [layer] = QgsProject.instance().mapLayers().values()
        assert layer.name() == "dem"
        assert layer.renderer().type() == "multibandcolor"


class TestLoginRetry:
    def test_login_refetches_placeholders_opened_while_logged_out(
        self, env, monkeypatch
    ):
        from qgis.core import QgsProject

        from plugin_dir.kumoy import session
        from plugin_dir.ui.layers import raster as raster_layers

        layer = _layer()
        QgsProject.instance().addMapLayer(layer)
        env.fetches.clear()  # the constructor's attempt failed: not logged in

        monkeypatch.setattr(session, "is_logged_in", lambda: False)
        raster_layers._on_session_changed()
        assert env.fetches == []

        monkeypatch.setattr(session, "is_logged_in", lambda: True)
        raster_layers._on_session_changed()
        assert [f[:2] for f in env.fetches] == [("r-2", "dem")]
