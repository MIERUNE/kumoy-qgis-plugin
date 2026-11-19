"""Maps through the "kumoy" project storage: save (with sprites) and read."""

import pytest

from .conftest import pump, wait_for_tasks, wait_until


@pytest.fixture(scope="module")
def point_vector(project):
    from qgis.core import QgsGeometry, QgsPointXY

    from plugin_dir.kumoy import api

    qv = api.qgis_vector
    vector_id = api.vector.create_vector(project.id, "e2e-map-points", "POINT")
    qv.add_attributes(vector_id, [{"name": "name", "type": "string"}])
    wkb = bytes(QgsGeometry.fromPointXY(QgsPointXY(141.35, 43.06)).asWkb())
    qv.add_features(
        vector_id, [{"kumoy_wkb": qv.encode_wkb(wkb), "properties": {"name": "a"}}]
    )
    yield api.vector.get_vector(vector_id)
    api.vector.delete_vector(vector_id)


@pytest.fixture
def styled_map(project):
    from plugin_dir.kumoy import api, map_project

    created = api.styledmap.create_styled_map(
        project.id, "e2e-map", map_project.empty_project_xml()
    )
    yield created
    api.styledmap.delete_styled_map(created.id)


@pytest.fixture
def qgs_project():
    from qgis.core import QgsProject

    project = QgsProject.instance()
    project.clear()
    yield project
    wait_for_tasks()
    project.clear()
    pump(0.1)


def _add_kumoy_layer(project, vector):
    from plugin_dir.kumoy.vector_layer import create_vector_layer

    layer = create_vector_layer(vector)
    project.addMapLayer(layer)
    wait_for_tasks()
    pump(0.1)
    wait_until(lambda: layer.featureCount() == 1, 30, "vector download")
    return layer


def test_save_and_read_map(project, point_vector, styled_map, qgs_project):
    from qgis.core import QgsMarkerSymbol, QgsSingleSymbolRenderer

    from plugin_dir.kumoy import api, map_project

    uri = map_project.map_uri(styled_map.id)
    layer = _add_kumoy_layer(qgs_project, point_vector)

    # A point layer renders as sprite on the web map: uploaded with the save
    assert qgs_project.write(uri)
    assert qgs_project.fileName() == uri
    assert not qgs_project.isDirty()
    saved = api.styledmap.get_styled_map(styled_map.id)
    assert point_vector.id in saved.qgisproject
    assert saved.assetsHash and saved.assetsHash.startswith("v2-")
    first_hash = saved.assetsHash

    # Same symbols, same hash
    assert qgs_project.write(uri)
    assert api.styledmap.get_styled_map(styled_map.id).assetsHash == first_hash

    # Another symbol: a new sprite
    layer.setRenderer(
        QgsSingleSymbolRenderer(
            QgsMarkerSymbol.createSimple({"name": "star", "size": "8"})
        )
    )
    assert qgs_project.write(uri)
    second_hash = api.styledmap.get_styled_map(styled_map.id).assetsHash
    assert second_hash.startswith("v2-") and second_hash != first_hash

    # Read it back through the storage
    qgs_project.clear()
    assert qgs_project.read(uri)
    pump(0.2)
    assert qgs_project.fileName() == uri
    assert qgs_project.title() == "e2e-map"
    layers = list(qgs_project.mapLayers().values())
    assert [lyr.providerType() for lyr in layers] == ["kumoy"]
    read_layer = layers[0]
    assert read_layer.isValid()
    assert read_layer.renderer().symbol().symbolLayer(0).shape() is not None
    wait_until(lambda: read_layer.featureCount() == 1, 30, "features")

    # No marker layer left: the sprite is cleared
    qgs_project.removeMapLayer(read_layer.id())
    assert qgs_project.write(uri)
    assert api.styledmap.get_styled_map(styled_map.id).assetsHash is None


def test_save_converts_local_layers(project, styled_map, qgs_project, monkeypatch):
    """Saving a map uploads its local layers first (the user picks them)."""
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer

    from plugin_dir.kumoy import api, map_project
    from plugin_dir.pyqt_version import QDIALOG_CODE
    from plugin_dir.ui.layers import convert
    from plugin_dir.ui.utils import uri_param

    def accept_all(dialog):
        for checkbox in dialog._checkboxes:
            checkbox.setChecked(True)
        return QDIALOG_CODE.Accepted

    monkeypatch.setattr(convert, "exec_dialog", accept_all)
    local = QgsVectorLayer("Point?crs=EPSG:4326&field=name:string", "local", "memory")
    f = QgsFeature(local.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(141, 43)))
    f.setAttributes(["x"])
    local.dataProvider().addFeatures([f])
    qgs_project.addMapLayer(local)

    assert qgs_project.write(map_project.map_uri(styled_map.id))
    layers = list(qgs_project.mapLayers().values())
    assert [lyr.providerType() for lyr in layers] == ["kumoy"]
    vector_id = uri_param(layers[0].source(), "vector_id")
    try:
        saved = api.styledmap.get_styled_map(styled_map.id)
        assert vector_id in saved.qgisproject
        assert "memory" not in saved.qgisproject
        assert saved.assetsHash  # the converted point layer has a sprite
    finally:
        wait_for_tasks()
        api.vector.delete_vector(vector_id)


def test_save_rejects_layers_of_another_project(
    project, point_vector, styled_map, qgs_project
):
    """A map can only use layers of its own Kumoy project."""
    from plugin_dir.kumoy import api, map_project

    other = api.project.create_project(project.teamId, "e2e-other")
    try:
        other_map = api.styledmap.create_styled_map(
            other.id, "e2e-other-map", map_project.empty_project_xml()
        )
        _add_kumoy_layer(qgs_project, point_vector)
        assert not qgs_project.write(map_project.map_uri(other_map.id))
        assert qgs_project.isDirty()
        assert (
            api.styledmap.get_styled_map(other_map.id).qgisproject.find(point_vector.id)
            == -1
        )
    finally:
        api.project.delete_project(other.id)


def test_read_missing_map_fails(qgs_project):
    from plugin_dir.kumoy import map_project

    assert not qgs_project.read(
        map_project.map_uri("00000000-0000-0000-0000-000000000000")
    )
