"""kumoy.api against the real server: parsing, error mapping, sign-out."""

import os
import uuid

import pytest

from .conftest import interactive_login, require_interactive


def _point(wkb: bytes):
    from qgis.core import QgsGeometry

    geometry = QgsGeometry()
    geometry.fromWkb(wkb)
    return geometry.asPoint()


@pytest.fixture
def api(token):
    from plugin_dir.kumoy import api

    return api


def test_user_and_public_params(api):
    me = api.user.get_me()
    assert me.id and me.email
    params = api.user.get_public_params()
    assert params.minQgisPluginVersion


def test_organization_endpoints(api, project):
    org_id = project.team.organizationId
    orgs = api.organization.get_organizations()
    org = next(o for o in orgs if o.id == org_id)
    assert org.role == "OWNER"

    detail = api.organization.get_organization(org_id)
    assert detail.subscriptionPlan
    assert detail.planSettings.maxVectors > 0
    assert detail.availableStorageUnits > 0
    assert detail.usage.projects >= 1

    projects = api.organization.get_projects(org_id)
    assert project.id in [p.id for p in projects]
    teams = api.organization.get_my_teams(org_id)
    assert [t.role for t in teams if t.id == project.teamId] == ["ADMIN"]


def test_project_crud(api, project):
    assert project.role in ("ADMIN", "OWNER")
    assert project.team.organizationId

    created = api.project.create_project(project.teamId, "e2e-crud", "desc")
    try:
        updated = api.project.update_project(created.id, name="e2e-crud2")
        assert updated.name == "e2e-crud2"
        # Not passed: kept
        assert api.project.get_project(created.id).description == "desc"
    finally:
        api.project.delete_project(created.id)
    with pytest.raises(api.error.NotFoundError):
        api.project.get_project(created.id)


def test_vector_endpoints(api, project):
    vector_id = api.vector.create_vector(project.id, "e2e-api", "POINT", "attr")
    try:
        assert vector_id in [v.id for v in api.vector.get_vectors(project.id)]
        detail = api.vector.get_vector(vector_id)
        assert (detail.type, detail.attribution, detail.count) == ("POINT", "attr", 0)
        assert detail.role in ("ADMIN", "OWNER")
        updated = api.vector.update_vector(vector_id, name="e2e-api2")
        assert updated.name == "e2e-api2"
        assert updated.attribution == "attr"

        vector, server_time = api.qgis_vector.get_vector_and_server_time(vector_id)
        assert vector.id == vector_id
        assert server_time is not None and server_time.tzinfo is not None
    finally:
        api.vector.delete_vector(vector_id)
    with pytest.raises(api.error.NotFoundError):
        api.vector.get_vector(vector_id)


def test_feature_endpoints(api, project):
    from qgis.core import QgsGeometry, QgsPointXY

    qv = api.qgis_vector
    vector_id = api.vector.create_vector(project.id, "e2e-features", "POINT")
    try:
        qv.add_attributes(
            vector_id,
            [
                {"name": "name", "type": "string"},
                {"name": "n", "type": "integer"},
                {"name": "f", "type": "float"},
                {"name": "b", "type": "boolean"},
            ],
        )
        wkb = bytes(QgsGeometry.fromPointXY(QgsPointXY(1, 2)).asWkb())
        ids = qv.add_features(
            vector_id,
            [
                {
                    "kumoy_wkb": qv.encode_wkb(wkb),
                    "properties": {"name": f"p{i}", "n": i, "f": i / 2, "b": True},
                }
                for i in range(3)
            ],
        )
        assert len(ids) == 3 and all(isinstance(i, int) for i in ids)

        rows = qv.get_features(vector_id)
        assert [r["kumoy_id"] for r in rows] == sorted(ids)
        assert _point(rows[0]["kumoy_wkb"]) == QgsPointXY(1, 2)
        assert rows[0]["properties"]["name"] == "p0"
        assert qv.get_features(vector_id, after_id=ids[-1]) == []

        _, server_time = qv.get_vector_and_server_time(vector_id)
        since = (server_time.replace(microsecond=0)).strftime("%Y-%m-%dT%H:%M:%SZ")
        qv.change_attribute_values(
            vector_id, [{"kumoy_id": ids[0], "properties": {"name": "changed"}}]
        )
        moved = bytes(QgsGeometry.fromPointXY(QgsPointXY(3, 4)).asWkb())
        qv.change_geometry_values(
            vector_id, [{"kumoy_id": ids[1], "kumoy_wkb": qv.encode_wkb(moved)}]
        )
        qv.delete_features(vector_id, [ids[2]])
        diff = qv.get_diff(vector_id, since)
        updated = {r["kumoy_id"]: r for r in diff.updated_rows}
        assert set(updated) == {ids[0], ids[1]}
        assert updated[ids[0]]["properties"]["name"] == "changed"
        assert _point(updated[ids[1]]["kumoy_wkb"]) == QgsPointXY(3, 4)
        assert diff.deleted_ids == [ids[2]]

        qv.delete_attributes(vector_id, ["b"])
        columns = [c.name for c in api.vector.get_vector(vector_id).columns]
        assert columns == ["name", "n", "f"]
    finally:
        api.vector.delete_vector(vector_id)


def test_raster_endpoints(api, project):
    upload = api.raster.create_raster(project.id, "e2e-api-raster", 10, "attr")
    try:
        assert upload.upload_url.startswith("http")
        assert upload.raster_id in [r.id for r in api.raster.get_rasters(project.id)]
        detail = api.raster.get_raster(upload.raster_id)
        assert detail.name == "e2e-api-raster"
        assert detail.role in ("ADMIN", "OWNER")
        assert api.raster.update_raster(upload.raster_id, name="r2").name == "r2"
        assert api.raster.get_download_url(upload.raster_id).startswith("http")
    finally:
        api.raster.delete_raster(upload.raster_id)


def test_styled_map_endpoints(api, project):
    from plugin_dir.kumoy import map_project

    xml = map_project.empty_project_xml()
    created = api.styledmap.create_styled_map(project.id, "e2e-api-map", xml, "d")
    try:
        assert created.id in [m.id for m in api.styledmap.get_styled_maps(project.id)]
        detail = api.styledmap.get_styled_map(created.id)
        assert detail.qgisproject.startswith("<!DOCTYPE qgis")
        assert detail.role in ("ADMIN", "OWNER")
        assert detail.project.team.organizationId == project.team.organizationId

        updated = api.styledmap.update_styled_map(
            created.id, name="m2", isPublic=True, assetsHash="v2-abc"
        )
        assert (updated.name, updated.isPublic, updated.assetsHash) == (
            "m2",
            True,
            "v2-abc",
        )
        # Absent keys are kept; None clears the hash
        updated = api.styledmap.update_styled_map(created.id, assetsHash=None)
        assert (updated.name, updated.isPublic, updated.assetsHash) == (
            "m2",
            True,
            None,
        )

        urls = api.styledmap.get_sprite_upload_urls(created.id, 10, 10)
        assert urls.json.url.startswith("/") and urls.json.fields
        assert urls.png.filename.endswith("sprite.png")
    finally:
        api.styledmap.delete_styled_map(created.id)


def test_error_mapping(api, project):
    from plugin_dir.kumoy import session

    with pytest.raises(api.error.NotFoundError) as e:
        api.vector.get_vector(str(uuid.uuid4()))
    assert e.value.status == 404

    with pytest.raises(api.error.QuotaExceededError) as e:
        api.raster.create_raster(project.id, "too-big", 10**13)
    assert e.value.status == 429

    other = os.environ.get("KUMOY_E2E_OTHER_TOKEN")
    saved = session._token
    try:
        if other:
            session._token = other
            with pytest.raises(api.error.ForbiddenError) as e:
                api.project.get_project(project.id)
            assert e.value.status == 403
        session._token = "invalid-token"
        with pytest.raises(api.error.UnauthorizedError) as e:
            api.user.get_me()
        assert e.value.status == 401
    finally:
        session._token = saved


def test_network_error(api, monkeypatch):
    from plugin_dir.kumoy import settings_manager

    monkeypatch.setattr(
        settings_manager, "custom_server_url", lambda: "http://127.0.0.1:9"
    )
    with pytest.raises(api.error.NetworkError):
        api.user.get_public_params()


def test_sign_out_revokes_token(api, pytestconfig):
    from plugin_dir.kumoy import session

    require_interactive()
    second = interactive_login(pytestconfig)
    saved = session._token
    try:
        session._token = second.access_token
        assert api.user.get_me().id
        api.auth.sign_out(second.access_token, second.refresh_token)
        with pytest.raises(api.error.UnauthorizedError):
            api.user.get_me()
    finally:
        session._token = saved
    # Other sessions stay valid
    assert api.user.get_me().id
