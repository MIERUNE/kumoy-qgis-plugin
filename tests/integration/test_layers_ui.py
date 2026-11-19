"""UI layer flows with real uploads: conversion, and recovery after login."""

import pytest

from .conftest import pump, wait_for_tasks, wait_until
from .test_raster import write_geotiff
from .test_vector import _memory_layer


@pytest.fixture
def qgs_project(project):
    from qgis.core import QgsProject

    qgs = QgsProject.instance()
    qgs.clear()
    yield qgs
    wait_for_tasks()
    qgs.clear()
    pump(0.1)


def _delete_uploaded(qgs):
    from plugin_dir.kumoy import api
    from plugin_dir.ui.utils import uri_param

    for layer in list(qgs.mapLayers().values()):
        if layer.providerType() == "kumoy":
            api.vector.delete_vector(uri_param(layer.source(), "vector_id"))
        elif layer.providerType() == "kumoyraster":
            api.raster.delete_raster(uri_param(layer.source(), "raster_id"))


def test_upload_vector_helper(project, qgs_project):
    """ui.layers._upload_vector.upload: background upload, then the layer."""
    from plugin_dir.ui.layers import _upload_vector

    source = _memory_layer()
    outcome, progress = [], []
    _upload_vector.upload(
        source,
        project.id,
        "e2e-helper",
        on_progress=progress.append,
        on_done=lambda layer: outcome.append(("done", layer)),
        on_error=lambda e: outcome.append(("error", e)),
    )
    wait_until(lambda: outcome, 60, "upload")
    kind, layer = outcome[0]
    assert kind == "done", layer
    assert layer.isValid() and layer.providerType() == "kumoy"
    assert layer.name() == "e2e-helper"
    assert progress and max(progress) == 100
    qgs_project.addMapLayer(layer)
    try:
        wait_until(lambda: layer.featureCount() == 3, 30, "features")
    finally:
        _delete_uploaded(qgs_project)


def test_convert_local_layers(project, qgs_project, tmp_path, monkeypatch):
    """The batch conversion run by the map save, with one vector and one raster."""
    from qgis.core import QgsRasterLayer

    from plugin_dir.pyqt_version import QDIALOG_CODE
    from plugin_dir.ui.layers import convert

    def accept_all(dialog):
        for checkbox in dialog._checkboxes:
            checkbox.setChecked(True)
        return QDIALOG_CODE.Accepted

    monkeypatch.setattr(convert, "exec_dialog", accept_all)

    path = str(tmp_path / "local.tif")
    write_geotiff(path)
    vector = _memory_layer()
    raster = QgsRasterLayer(path, "e2e-local-raster")
    qgs_project.addMapLayers([vector, raster])
    try:
        result = convert.convert_local_layers(project.id)
        assert result.errors == [] and result.skipped == []
        assert result.converted and not result.cancelled
        layers = {layer.name(): layer for layer in qgs_project.mapLayers().values()}
        assert {n: lyr.providerType() for n, lyr in layers.items()} == {
            "e2e-points": "kumoy",
            "e2e-local-raster": "kumoyraster",
        }
        # The raster's COG was kept as cache: it opens at once
        assert layers["e2e-local-raster"].width() == 4
        wait_until(lambda: layers["e2e-points"].featureCount() == 3, 30, "features")
    finally:
        _delete_uploaded(qgs_project)


def test_layers_recover_after_login(project, token, qgs_project, tmp_path):
    """A project opened while logged out comes alive once the user logs in."""
    import processing
    from qgis.core import QgsProject, QgsRasterLayer

    from plugin_dir.kumoy import api, local_cache, session
    from plugin_dir.kumoy.raster_layer import create_raster_layer
    from plugin_dir.kumoy.vector_layer import create_vector_layer
    from plugin_dir.ui.layers import raster as raster_layers
    from plugin_dir.ui.layers import vector as vector_layers

    # A saved project with a Kumoy vector and raster
    source = _memory_layer()
    vector_id = processing.run(
        "kumoy:uploadvector",
        {"INPUT": source, "PROJECT_ID": project.id, "VECTOR_NAME": "e2e-recover"},
    )["VECTOR_ID"]
    tif = str(tmp_path / "recover.tif")
    write_geotiff(tif)
    raster_id = processing.run(
        "kumoy:uploadraster",
        {"INPUT": QgsRasterLayer(tif, "r"), "PROJECT_ID": project.id},
    )["RASTER_ID"]
    saved = QgsProject()
    saved.addMapLayer(create_vector_layer(api.vector.get_vector(vector_id)))
    saved.addMapLayer(create_raster_layer(api.raster.get_raster(raster_id)))
    wait_for_tasks()
    project_file = str(tmp_path / "saved.qgs")
    assert saved.write(project_file)
    del saved

    vector_layers.register()
    raster_layers.register()
    try:
        # QGIS starts with the project before the session is loaded
        local_cache.vector.clear(vector_id)
        assert local_cache.raster.clear(raster_id)
        session._token = None
        assert qgs_project.read(project_file)
        wait_for_tasks()
        pump(0.2)
        by_key = {lyr.providerType(): lyr for lyr in qgs_project.mapLayers().values()}
        assert not by_key["kumoy"].isValid()
        assert by_key["kumoyraster"].dataProvider().xSize() == 0  # placeholder

        session._token = token
        session._notify()  # what set_token() does after storing the token
        by_key = {lyr.providerType(): lyr for lyr in qgs_project.mapLayers().values()}
        wait_until(lambda: by_key["kumoy"].isValid(), 30, "vector valid")
        wait_until(lambda: by_key["kumoy"].featureCount() == 3, 30, "features")
        wait_until(
            lambda: by_key["kumoyraster"].dataProvider().xSize() == 4,
            60,
            "raster loaded",
        )
        assert by_key["kumoyraster"].isValid()
    finally:
        session._token = token
        vector_layers.unregister()
        raster_layers.unregister()
        wait_for_tasks()
        api.vector.delete_vector(vector_id)
        api.raster.delete_raster(raster_id)
