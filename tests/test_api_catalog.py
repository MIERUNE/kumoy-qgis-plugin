"""kumoy.api.catalog のユニットテスト（ApiClient をモックする）"""

import pytest


@pytest.mark.usefixtures("qgis_plugin_path")
class TestGetCatalogs:
    def test_parses_list(self, monkeypatch):
        from plugin_dir.kumoy.api import catalog

        captured = {}

        def fake_get(endpoint, params=None):
            captured["endpoint"] = endpoint
            return [
                {
                    "id": "c-1",
                    "name": "基盤データ",
                    "description": "行政界・標高など",
                    "organizationId": "o-1",
                    "vectorCount": 3,
                    "rasterCount": 1,
                    "createdAt": "2026-01-01",
                    "updatedAt": "2026-01-02",
                }
            ]

        monkeypatch.setattr(catalog.ApiClient, "get", staticmethod(fake_get))

        result = catalog.get_catalogs("o-1")

        assert captured["endpoint"] == "/organization/o-1/catalogs"
        assert len(result) == 1
        assert result[0].id == "c-1"
        assert result[0].name == "基盤データ"
        assert result[0].vectorCount == 3
        assert result[0].rasterCount == 1

    def test_empty_list(self, monkeypatch):
        from plugin_dir.kumoy.api import catalog

        monkeypatch.setattr(
            catalog.ApiClient, "get", staticmethod(lambda endpoint, params=None: [])
        )

        assert catalog.get_catalogs("o-1") == []


@pytest.mark.usefixtures("qgis_plugin_path")
class TestGetCatalog:
    def test_parses_detail(self, monkeypatch):
        from plugin_dir.kumoy.api import catalog

        captured = {}

        def fake_get(endpoint, params=None):
            captured["endpoint"] = endpoint
            return {
                "id": "c-1",
                "name": "基盤データ",
                "description": "",
                "organizationId": "o-1",
                "role": "MEMBER",
                "vectors": [
                    {
                        "id": "v-1",
                        "name": "行政界",
                        "type": "POLYGON",
                        "storageUnits": 0.5,
                        "createdAt": "2026-01-01",
                        "updatedAt": "2026-01-02",
                    }
                ],
                "rasters": [
                    {
                        "id": "r-1",
                        "name": "標高",
                        "storageUnits": 1.5,
                        "createdAt": "2026-01-01",
                        "updatedAt": "2026-01-02",
                    }
                ],
                "createdAt": "2026-01-01",
                "updatedAt": "2026-01-02",
            }

        monkeypatch.setattr(catalog.ApiClient, "get", staticmethod(fake_get))

        result = catalog.get_catalog("c-1")

        assert captured["endpoint"] == "/catalog/c-1"
        assert result.role == "MEMBER"
        assert len(result.vectors) == 1
        assert result.vectors[0].id == "v-1"
        assert result.vectors[0].type == "POLYGON"
        assert len(result.rasters) == 1
        assert result.rasters[0].id == "r-1"
        assert result.rasters[0].storageUnits == 1.5

    def test_empty_catalog(self, monkeypatch):
        from plugin_dir.kumoy.api import catalog

        def fake_get(endpoint, params=None):
            return {
                "id": "c-1",
                "name": "empty",
                "description": "",
                "organizationId": "o-1",
                "role": "ADMIN",
                "vectors": [],
                "rasters": [],
                "createdAt": "2026-01-01",
                "updatedAt": "2026-01-02",
            }

        monkeypatch.setattr(catalog.ApiClient, "get", staticmethod(fake_get))

        result = catalog.get_catalog("c-1")

        assert result.vectors == []
        assert result.rasters == []
        assert result.role == "ADMIN"
