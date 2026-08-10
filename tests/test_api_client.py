import os
from types import SimpleNamespace

import pytest


@pytest.mark.usefixtures("qgis_plugin_path")
class TestPostBinaryToFile:
    def _setup(self, monkeypatch, payload, status_code=200, error=0):
        from qgis.PyQt.QtCore import QByteArray

        from plugin_dir.kumoy.api import client

        class FakeRequest:
            def setHeader(self, _header, _value):
                pass

        class FakeReply:
            def attribute(self, _attribute):
                return status_code

            def content(self):
                return QByteArray(payload)

            def rawHeader(self, name):
                if name == b"Content-Length":
                    return QByteArray(str(len(payload)).encode())
                return QByteArray()

        class FakeBlockingRequest:
            NoError = 0

            def __init__(self):
                self._reply = FakeReply()

            def post(self, _request, _body):
                return error

            def reply(self):
                return self._reply

            def errorMessage(self):
                return "network error"

        monkeypatch.setattr(
            client.api_config,
            "get_api_config",
            lambda: SimpleNamespace(SERVER_URL="https://example.test"),
        )
        monkeypatch.setattr(client, "_build_request", lambda _url: FakeRequest())
        monkeypatch.setattr(client, "QgsBlockingNetworkRequest", FakeBlockingRequest)
        return client

    def test_writes_successful_response_and_reports_progress(self, monkeypatch):
        payload = b"flatgeobuf-bytes"
        client = self._setup(monkeypatch, payload)
        progress = []

        path = client.ApiClient.post_binary_to_file(
            "/binary",
            {},
            lambda received, total: progress.append((received, total)),
            suffix=".fgb",
        )
        try:
            assert path.endswith(".fgb")
            with open(path, "rb") as file:
                assert file.read() == payload
            assert progress == [(len(payload), len(payload))]
        finally:
            os.unlink(path)

    def test_raises_typed_error_without_creating_output(self, monkeypatch):
        payload = b'{"message":"Validation Error","error":"bad body"}'
        client = self._setup(monkeypatch, payload, status_code=400, error=1)

        with pytest.raises(client.api_error.ValidateError, match="bad body"):
            client.ApiClient.post_binary_to_file("/binary", {})
