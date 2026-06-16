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
                "url": "https://s3.example.com/bucket",
                "fields": {"key": "raster/r-123/data.tif", "policy": "abc"},
            }

        monkeypatch.setattr(raster.ApiClient, "post", staticmethod(fake_post))

        result = raster.create_raster("p-1", "dem", 52428800)

        assert captured["endpoint"] == "/project/p-1/raster"
        assert captured["data"] == {"name": "dem", "bytes": 52428800}
        assert result.raster_id == "r-123"
        assert result.url == "https://s3.example.com/bucket"
        assert result.fields["key"] == "raster/r-123/data.tif"

    def test_includes_attribution_when_given(self, monkeypatch):
        raster = self._mod()
        captured = {}

        def fake_post(endpoint, data):
            captured["data"] = data
            return {"rasterId": "r", "url": "u", "fields": {}}

        monkeypatch.setattr(raster.ApiClient, "post", staticmethod(fake_post))

        raster.create_raster("p-1", "dem", 10, attribution="© me")

        assert captured["data"]["attribution"] == "© me"

    def test_omits_attribution_when_none(self, monkeypatch):
        raster = self._mod()
        captured = {}

        def fake_post(endpoint, data):
            captured["data"] = data
            return {"rasterId": "r", "url": "u", "fields": {}}

        monkeypatch.setattr(raster.ApiClient, "post", staticmethod(fake_post))

        raster.create_raster("p-1", "dem", 10)

        assert "attribution" not in captured["data"]


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
