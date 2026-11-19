"""Processing tools against the real server, through processing.run().

Output keys are a scripting API: the assertions pin them.
"""

import os

import pytest

from .conftest import pump, wait_for_tasks
from .test_raster import write_geotiff

VECTOR_KEYS = {"id", "name", "type", "projectId", "attribution", "createdAt"}


@pytest.fixture(scope="module")
def run(project):
    import processing

    def run_(alg_id, params):
        return processing.run(f"kumoy:{alg_id}", params)

    return run_


@pytest.fixture(scope="module")
def vector_id(project):
    from plugin_dir.kumoy import api

    vid = api.vector.create_vector(project.id, "e2e-proc-vector", "POINT")
    yield vid
    try:
        api.vector.delete_vector(vid)
    except api.error.NotFoundError:
        pass


def test_organizations_and_projects(run, project):
    orgs = run("listorganizations", {})["ORGANIZATIONS"]
    org = next(o for o in orgs if o["id"] == project.team.organizationId)
    assert {"id", "name", "role", "subscriptionPlan"} <= set(org)

    projects = run("listprojects", {"ORGANIZATION_ID": org["id"]})["PROJECTS"]
    listed = next(p for p in projects if p["id"] == project.id)
    assert {"id", "name", "vectorCount", "rasterCount", "mapCount"} <= set(listed)

    got = run("getproject", {"PROJECT": project.id})
    assert set(got) == {"PROJECT"}
    assert got["PROJECT"]["id"] == project.id
    assert got["PROJECT"]["role"] in ("ADMIN", "OWNER")


def test_vector_tools(run, project, vector_id):
    from qgis.core import QgsProcessingException

    vectors = run("listvectors", {"PROJECT_ID": project.id})["VECTORS"]
    listed = next(v for v in vectors if v["id"] == vector_id)
    assert VECTOR_KEYS <= set(listed)
    assert "project" not in listed

    got = run("getvector", {"VECTOR_ID": vector_id})["VECTOR"]
    assert got["type"] == "POINT" and "columns" in got

    updated = run(
        "updatevector",
        {"VECTOR_ID": vector_id, "NAME": "e2e-renamed", "ATTRIBUTION": ""},
    )["VECTOR"]
    assert updated["name"] == "e2e-renamed"

    check_add_to_map("kumoy:addvectortomap", {"VECTOR_ID": vector_id}, "kumoy")

    assert run("deletevector", {"VECTOR_ID": vector_id}) == {"VECTOR_ID": vector_id}
    with pytest.raises(QgsProcessingException):
        run("getvector", {"VECTOR_ID": vector_id})


def check_add_to_map(alg_id, params, provider_key):
    """The layer goes to the context, loaded into the project on completion."""
    import processing
    from qgis.core import QgsProcessingContext, QgsProject

    context = QgsProcessingContext()
    context.setProject(QgsProject.instance())
    layer = processing.run(alg_id, params, context=context)["OUTPUT"]
    assert layer.isValid() and layer.providerType() == provider_key
    assert list(context.layersToLoadOnCompletion()) == [layer.id()]
    wait_for_tasks()
    context.temporaryLayerStore().removeAllMapLayers()


def test_raster_tools(run, project, tmp_path):
    from qgis.core import QgsProcessingException, QgsRasterLayer

    path = str(tmp_path / "proc.tif")
    write_geotiff(path)
    source = QgsRasterLayer(path, "proc")
    raster_id = run("uploadraster", {"INPUT": source, "PROJECT_ID": project.id})[
        "RASTER_ID"
    ]
    # pytest.raises below keeps this frame alive; a layer that outlives QGIS
    # crashes the interpreter at exit
    del source
    rasters = run("listrasters", {"PROJECT_ID": project.id})["RASTERS"]
    assert raster_id in [r["id"] for r in rasters]
    got = run("getraster", {"RASTER_ID": raster_id})["RASTER"]
    assert got["name"] == "proc" and got["bytes"] > 0
    updated = run("updateraster", {"RASTER_ID": raster_id, "NAME": "proc2"})["RASTER"]
    assert updated["name"] == "proc2"

    check_add_to_map("kumoy:addrastertomap", {"RASTER_ID": raster_id}, "kumoyraster")

    assert run("deleteraster", {"RASTER_ID": raster_id}) == {"RASTER_ID": raster_id}
    with pytest.raises(QgsProcessingException):
        run("getraster", {"RASTER_ID": raster_id})


def test_map_tools(run, project, tmp_path):
    from qgis.core import QgsProject, QgsVectorLayer

    from plugin_dir.kumoy import api
    from plugin_dir.kumoy.vector_layer import create_vector_layer

    # A project file with a Kumoy point layer, whose symbol needs a sprite
    vid = api.vector.create_vector(project.id, "e2e-proc-map", "POINT")
    try:
        qgs = QgsProject()
        layer = create_vector_layer(api.vector.get_vector(vid))
        assert isinstance(layer, QgsVectorLayer)
        qgs.addMapLayer(layer)
        project_file = str(tmp_path / "in.qgz")
        assert qgs.write(project_file)
        wait_for_tasks()

        created = run(
            "createmap",
            {
                "NAME": "e2e-proc-map",
                "DESCRIPTION": "d",
                "IS_PUBLIC": False,
                "PROJECT_FILE": project_file,
            },
        )["MAP"]
        assert "qgisproject" not in created
        assert created["projectId"] == project.id
        assert created["assetsHash"].startswith("v2-")
        map_id = created["id"]

        maps = run("listmaps", {"PROJECT_ID": project.id})["MAPS"]
        assert map_id in [m["id"] for m in maps]

        out = str(tmp_path / "out.qgs")
        got = run("getmap", {"MAP_ID": map_id, "PROJECT_FILE": out})
        assert set(got) == {"MAP", "PROJECT_FILE"}
        assert got["MAP"]["role"] in ("ADMIN", "OWNER")
        with open(out, encoding="utf-8") as f:
            assert vid in f.read()

        updated = run(
            "updatemap", {"MAP_ID": map_id, "NAME": "e2e-proc-map2", "IS_PUBLIC": 1}
        )["MAP"]
        assert (updated["name"], updated["isPublic"]) == ("e2e-proc-map2", True)
        assert updated["description"] == "d"  # empty fields are kept

        # Replacing the project with one without marker layers clears the sprite
        empty_file = str(tmp_path / "empty.qgs")
        assert QgsProject().write(empty_file)
        updated = run("updatemap", {"MAP_ID": map_id, "PROJECT_FILE": empty_file})[
            "MAP"
        ]
        assert updated["assetsHash"] is None

        assert run("deletemap", {"MAP_ID": map_id}) == {"MAP_ID": map_id}
    finally:
        api.vector.delete_vector(vid)
        if os.path.exists(str(tmp_path / "in.qgz")):
            os.remove(str(tmp_path / "in.qgz"))


def test_not_logged_in(run):
    from qgis.core import QgsProcessingException

    from plugin_dir.kumoy import session

    saved = session._token
    session._token = None
    try:
        with pytest.raises(QgsProcessingException, match="not logged in"):
            run("listorganizations", {})
    finally:
        session._token = saved


def test_expired_session(run, dialogs):
    """401 fails the tool; in the GUI it also ends the session (and offers login)."""
    from qgis.core import QgsProcessingContext, QgsProcessingException

    import processing
    from plugin_dir.kumoy import session

    saved = session._token
    try:
        # qgis_process / scripts without a project: no GUI side effects
        session._token = "revoked"
        with pytest.raises(QgsProcessingException, match="expired"):
            processing.run(
                "kumoy:listorganizations", {}, context=QgsProcessingContext()
            )
        assert session.get_token() == "revoked"
        assert not dialogs

        with pytest.raises(QgsProcessingException, match="expired"):
            run("listorganizations", {})
        pump(0.2)  # the session-expired handling is queued
        assert session.get_token() is None
        assert [d[0] for d in dialogs] == ["exec"]  # "Session expired"
    finally:
        session._token = saved
