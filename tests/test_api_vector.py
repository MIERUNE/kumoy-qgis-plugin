"""kumoy.api.vector のユニットテスト（ApiClient をモックする）

Catalog対応で projectId/project が nullable になったため、
Project所有・Catalog所有それぞれのレスポンスのパースを検証する。
"""

import pytest


def _project_payload():
    return {
        "id": "p-1",
        "name": "proj",
        "description": "",
        "createdAt": "2026-01-01",
        "updatedAt": "2026-01-02",
        "team": {
            "id": "t-1",
            "name": "team",
            "createdAt": "2026-01-01",
            "updatedAt": "2026-01-02",
            "organizationId": "o-1",
            "organization": {
                "id": "o-1",
                "name": "org",
                "subscriptionPlan": "FREE",
                "stripeCustomerId": None,
                "storageUnits": 0,
                "createdAt": "2026-01-01",
                "updatedAt": "2026-01-02",
            },
        },
    }


@pytest.mark.usefixtures("qgis_plugin_path")
class TestGetVector:
    def test_parses_project_owned(self, monkeypatch):
        from plugin_dir.kumoy.api import vector

        def fake_get(endpoint, params=None):
            return {
                "id": "v-1",
                "name": "roads",
                "type": "LINESTRING",
                "projectId": "p-1",
                "catalogId": None,
                "project": _project_payload(),
                "attribution": "© me",
                "storageUnits": 0.5,
                "role": "ADMIN",
                "extent": [130.0, 30.0, 140.0, 40.0],
                "count": 10,
                "columns": [],
                "createdAt": "2026-01-01",
                "updatedAt": "2026-01-02",
            }

        monkeypatch.setattr(vector.ApiClient, "get", staticmethod(fake_get))

        result = vector.get_vector("v-1")

        assert result.projectId == "p-1"
        assert result.catalogId is None
        assert result.project is not None
        assert result.project.team.organization.id == "o-1"
        assert result.role == "ADMIN"

    def test_parses_catalog_owned(self, monkeypatch):
        from plugin_dir.kumoy.api import vector

        def fake_get(endpoint, params=None):
            return {
                "id": "v-1",
                "name": "admin-boundary",
                "type": "POLYGON",
                "projectId": None,
                "catalogId": "c-1",
                "project": None,
                "attribution": "",
                "storageUnits": 0.5,
                "role": "MEMBER",
                "extent": [130.0, 30.0, 140.0, 40.0],
                "count": 10,
                "columns": [],
                "createdAt": "2026-01-01",
                "updatedAt": "2026-01-02",
            }

        monkeypatch.setattr(vector.ApiClient, "get", staticmethod(fake_get))

        result = vector.get_vector("v-1")

        assert result.projectId is None
        assert result.catalogId == "c-1"
        assert result.project is None
        assert result.role == "MEMBER"


@pytest.mark.usefixtures("qgis_plugin_path")
class TestAddVectorToCatalog:
    def test_sends_payload_to_catalog_endpoint(self, monkeypatch):
        from plugin_dir.kumoy.api import vector

        captured = {}

        def fake_post(endpoint, data):
            captured["endpoint"] = endpoint
            captured["data"] = data
            return {
                "id": "v-1",
                "name": "roads",
                "uri": "kumoy://v-1",
                "type": "LINESTRING",
                "projectId": None,
                "catalogId": "c-1",
                "attribution": "",
                "bytes": 0,
                "createdAt": "2026-01-01",
                "updatedAt": "2026-01-02",
            }

        monkeypatch.setattr(vector.ApiClient, "post", staticmethod(fake_post))

        result = vector.add_vector_to_catalog(
            "c-1", vector.AddVectorOptions(name="roads", type="LINESTRING")
        )

        assert captured["endpoint"] == "/catalog/c-1/vector"
        assert captured["data"] == {"name": "roads", "type": "LINESTRING"}
        assert result.id == "v-1"
        assert result.projectId is None
        assert result.catalogId == "c-1"


@pytest.mark.usefixtures("qgis_plugin_path")
class TestGetVectors:
    def test_parses_list(self, monkeypatch):
        from plugin_dir.kumoy.api import vector

        captured = {}

        def fake_get(endpoint, params=None):
            captured["endpoint"] = endpoint
            return [
                {
                    "id": "v-1",
                    "name": "roads",
                    "type": "LINESTRING",
                    "projectId": "p-1",
                    "catalogId": None,
                    "project": _project_payload(),
                    "attribution": "",
                    "storageUnits": 0.5,
                    "createdAt": "2026-01-01",
                    "updatedAt": "2026-01-02",
                }
            ]

        monkeypatch.setattr(vector.ApiClient, "get", staticmethod(fake_get))

        result = vector.get_vectors("p-1")

        assert captured["endpoint"] == "/project/p-1/vector"
        assert len(result) == 1
        assert result[0].projectId == "p-1"
        assert result[0].catalogId is None
        assert result[0].project.id == "p-1"
