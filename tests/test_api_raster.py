"""kumoy.api.raster のユニットテスト（ApiClient をモックする）"""

import pytest


@pytest.mark.usefixtures("qgis_plugin_path")
class TestCreateRaster:
    def _mod(self):
        from plugin_dir.kumoy.api import raster

        return raster

    def test_sends_payload_and_parses_presigned(self, monkeypatch):
        raster = self._mod()
        captured = {}

        def fake_post(endpoint, data):
            captured["endpoint"] = endpoint
            captured["data"] = data
            return {
                "rasterId": "r-123",
                "uploadUrl": "https://s3.example.com/bucket/raster/r-123/data.tif?X-Amz-Signature=abc",
            }

        monkeypatch.setattr(raster.ApiClient, "post", staticmethod(fake_post))

        result = raster.create_raster("p-1", "dem", 52428800)

        assert captured["endpoint"] == "/project/p-1/raster"
        assert captured["data"] == {"name": "dem", "bytes": 52428800}
        assert result.raster_id == "r-123"
        assert "X-Amz-Signature" in result.upload_url

    def test_includes_attribution_when_given(self, monkeypatch):
        raster = self._mod()
        captured = {}

        def fake_post(endpoint, data):
            captured["data"] = data
            return {"rasterId": "r", "uploadUrl": "https://s3.example.com/key?sig=x"}

        monkeypatch.setattr(raster.ApiClient, "post", staticmethod(fake_post))

        raster.create_raster("p-1", "dem", 10, attribution="© me")

        assert captured["data"]["attribution"] == "© me"

    def test_omits_attribution_when_none(self, monkeypatch):
        raster = self._mod()
        captured = {}

        def fake_post(endpoint, data):
            captured["data"] = data
            return {"rasterId": "r", "uploadUrl": "https://s3.example.com/key?sig=x"}

        monkeypatch.setattr(raster.ApiClient, "post", staticmethod(fake_post))

        raster.create_raster("p-1", "dem", 10)

        assert "attribution" not in captured["data"]


@pytest.mark.usefixtures("qgis_plugin_path")
class TestGetRasters:
    def test_parses_list(self, monkeypatch):
        from plugin_dir.kumoy.api import raster

        captured = {}

        def fake_get(endpoint, params=None):
            captured["endpoint"] = endpoint
            return [
                {
                    "id": "r-1",
                    "name": "dem",
                    "projectId": "p-1",
                    "attribution": "© me",
                    "bytes": 100,
                    "createdAt": "2026-01-01",
                    "updatedAt": "2026-01-02",
                }
            ]

        monkeypatch.setattr(raster.ApiClient, "get", staticmethod(fake_get))

        result = raster.get_rasters("p-1")

        assert captured["endpoint"] == "/project/p-1/raster"
        assert len(result) == 1
        assert result[0].id == "r-1"
        assert result[0].name == "dem"
        assert result[0].bytes == 100

    def test_empty_list(self, monkeypatch):
        from plugin_dir.kumoy.api import raster

        monkeypatch.setattr(
            raster.ApiClient, "get", staticmethod(lambda endpoint, params=None: [])
        )

        assert raster.get_rasters("p-1") == []


@pytest.mark.usefixtures("qgis_plugin_path")
class TestGetRaster:
    def test_parses_detail_with_role(self, monkeypatch):
        from plugin_dir.kumoy.api import raster

        captured = {}

        def fake_get(endpoint, params=None):
            captured["endpoint"] = endpoint
            return {
                "id": "r-1",
                "name": "dem",
                "projectId": "p-1",
                "attribution": "© me",
                "bytes": 100,
                "role": "OWNER",
                "createdAt": "2026-01-01",
                "updatedAt": "2026-01-02",
            }

        monkeypatch.setattr(raster.ApiClient, "get", staticmethod(fake_get))

        result = raster.get_raster("r-1")

        assert captured["endpoint"] == "/raster/r-1"
        assert result.id == "r-1"
        assert result.role == "OWNER"

    def test_defaults_role_to_member(self, monkeypatch):
        from plugin_dir.kumoy.api import raster

        monkeypatch.setattr(
            raster.ApiClient, "get", staticmethod(lambda endpoint, params=None: {})
        )

        assert raster.get_raster("r-1").role == "MEMBER"


@pytest.mark.usefixtures("qgis_plugin_path")
class TestGetDownloadUrl:
    def test_returns_presigned_url(self, monkeypatch):
        from plugin_dir.kumoy.api import raster

        captured = {}

        def fake_get(endpoint, params=None):
            captured["endpoint"] = endpoint
            return {"url": "https://s3.example.com/key?X-Amz-Signature=abc"}

        monkeypatch.setattr(raster.ApiClient, "get", staticmethod(fake_get))

        url = raster.get_download_url("r-9")

        assert captured["endpoint"] == "/raster/r-9/download"
        assert "X-Amz-Signature" in url

    def test_returns_empty_when_missing(self, monkeypatch):
        from plugin_dir.kumoy.api import raster

        monkeypatch.setattr(
            raster.ApiClient, "get", staticmethod(lambda endpoint, params=None: {})
        )

        assert raster.get_download_url("r-9") == ""


@pytest.mark.usefixtures("qgis_plugin_path")
class TestDeleteRaster:
    def test_calls_delete_endpoint(self, monkeypatch):
        from plugin_dir.kumoy.api import raster

        captured = {}
        monkeypatch.setattr(
            raster.ApiClient,
            "delete",
            staticmethod(lambda endpoint: captured.setdefault("endpoint", endpoint)),
        )

        raster.delete_raster("r-9")

        assert captured["endpoint"] == "/raster/r-9"
