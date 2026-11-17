"""kumoy.api.raster: endpoints and payloads (the HTTP client is mocked)."""

import pytest


@pytest.fixture
def raster_api(qgis_app, monkeypatch):
    from plugin_dir.kumoy.api import raster

    calls = []

    def fake(method):
        def call(path, *args, **kwargs):
            calls.append((method, path, args[0] if args else None))
            return fake.responses.pop(0)

        return call

    fake.responses = []
    for method in ("get", "post", "put", "delete"):
        monkeypatch.setattr(raster.client, method, fake(method))
    raster.calls = calls
    raster.responses = fake.responses
    return raster


def test_create_raster_sends_name_bytes_attribution(raster_api):
    raster_api.responses.append(
        {"rasterId": "r-1", "uploadUrl": "https://s3/k?X-Amz-Signature=x"}
    )

    result = raster_api.create_raster("p-1", "dem", 52428800)

    assert raster_api.calls == [
        (
            "post",
            "/project/p-1/raster",
            {"name": "dem", "bytes": 52428800, "attribution": ""},
        )
    ]
    assert result.raster_id == "r-1"
    assert result.upload_url.endswith("X-Amz-Signature=x")


def test_get_rasters_parses_list(raster_api):
    raster_api.responses.append([{"id": "r-1", "name": "dem", "projectId": "p-1"}])

    rasters = raster_api.get_rasters("p-1")

    assert raster_api.calls[0][:2] == ("get", "/project/p-1/raster")
    assert [(r.id, r.name, r.projectId) for r in rasters] == [("r-1", "dem", "p-1")]


def test_get_raster_parses_detail(raster_api):
    raster_api.responses.append(
        {"id": "r-1", "name": "dem", "role": "ADMIN", "bandCount": 3}
    )

    detail = raster_api.get_raster("r-1")

    assert raster_api.calls[0][:2] == ("get", "/raster/r-1")
    assert (detail.role, detail.bandCount) == ("ADMIN", 3)


def test_get_download_url(raster_api):
    raster_api.responses.append({"url": "https://s3/k?sig"})

    assert raster_api.get_download_url("r-9") == "https://s3/k?sig"
    assert raster_api.calls[0][:2] == ("get", "/raster/r-9/download")


def test_update_raster_sends_only_given_fields(raster_api):
    raster_api.responses.append({"id": "r-1", "name": "renamed"})

    result = raster_api.update_raster("r-1", name="renamed")

    assert raster_api.calls == [("put", "/raster/r-1", {"name": "renamed"})]
    assert result.name == "renamed"


def test_delete_raster(raster_api):
    raster_api.responses.append(None)

    raster_api.delete_raster("r-9")

    assert raster_api.calls == [("delete", "/raster/r-9", None)]
