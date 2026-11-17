"""Raster round trip: upload tool (COG + presigned PUT), download, layer."""

import struct

import pytest

from .conftest import wait_for_tasks, wait_until


def write_geotiff(path: str) -> None:
    """4x4 Float32 GeoTIFF in EPSG:4326 whose pixel (col, row) is row * 4 + col."""
    from osgeo import gdal, osr

    ds = gdal.GetDriverByName("GTiff").Create(path, 4, 4, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((140.0, 0.25, 0, 44.0, 0, -0.25))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).WriteRaster(0, 0, 4, 4, struct.pack("16f", *range(16)))
    ds.FlushCache()


@pytest.fixture(scope="module")
def uploaded(project, tmp_path_factory):
    import processing
    from qgis.core import QgsRasterLayer

    from plugin_dir.kumoy import api

    path = str(tmp_path_factory.mktemp("raster") / "tiny.tif")
    write_geotiff(path)
    source = QgsRasterLayer(path, "tiny")
    assert source.isValid()
    result = processing.run(
        "kumoy:uploadraster",
        {"INPUT": source, "PROJECT_ID": project.id, "RASTER_NAME": "e2e-raster"},
    )
    raster = api.raster.get_raster(result["RASTER_ID"])
    yield raster
    api.raster.delete_raster(raster.id)


def test_upload_tool(uploaded):
    assert uploaded.name == "e2e-raster"
    assert uploaded.bytes > 0
    # fileStatus / bandCount come from the raster service, which the local
    # setup does not run (only tiles need it)


def test_download_and_open(uploaded):
    from qgis.core import QgsPointXY

    from plugin_dir.kumoy import download, local_cache
    from plugin_dir.kumoy.raster_layer import create_raster_layer
    from plugin_dir.kumoy.tasks import run_task

    # The upload kept the COG as cache; download it for real
    assert local_cache.raster.is_cached(uploaded.id)
    assert local_cache.raster.clear(uploaded.id)
    results = []
    run_task(
        "download",
        lambda t: download.download_raster(uploaded.id, t.setProgress, t.isCanceled),
        results.append,
        results.append,
    )
    wait_until(lambda: results, 60, "raster download")
    assert results[0] == local_cache.raster.get_cache_path(uploaded.id)

    layer = create_raster_layer(uploaded)
    assert layer.isValid()
    assert layer.width() == 4 and layer.height() == 4
    assert layer.crs().authid() == "EPSG:4326"
    value, ok = layer.dataProvider().sample(QgsPointXY(140.3, 43.6), 1)
    assert ok and value == 5.0  # col 1, row 1


def test_placeholder_downloads_in_background(uploaded):
    """Opening an uncached raster never blocks: it downloads in a task."""
    from plugin_dir.kumoy import download, local_cache
    from plugin_dir.kumoy.raster_layer import create_raster_layer

    wait_for_tasks()
    assert local_cache.raster.clear(uploaded.id)
    ready = []
    download.fetcher.ready.connect(ready.append)
    try:
        layer = create_raster_layer(uploaded)
        assert layer.isValid()  # placeholder
        wait_until(lambda: uploaded.id in ready, 60, "background download")
        assert local_cache.raster.is_cached(uploaded.id)
    finally:
        download.fetcher.ready.disconnect(ready.append)
