import base64
import http.server
import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from qgis.core import QgsField, QgsFields, QgsGeometry, QgsVectorLayer, QgsWkbTypes
from qgis.PyQt.QtCore import QVariant


FIXTURE = Path(__file__).parent / "fixtures" / "flatgeobuf" / "postgis-chunked.fgb"


class _Handler(http.server.BaseHTTPRequestHandler):
    v2_rows = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)

        if self.path.endswith("/get-features-v3"):
            if "/fallback/" in self.path:
                self._send_json(
                    404, {"message": "Not Found", "error": "v3 unavailable"}
                )
                return
            payload = FIXTURE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-flatgeobuf")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if self.path.endswith("/get-features-v2"):
            self._send_json(200, self.v2_rows)
            return

        self._send_json(404, {"message": "Not Found", "error": "unknown route"})

    def _send_json(self, status, body):
        payload = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


@pytest.fixture
def fgb_server():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    yield f"http://{host}:{port}"
    httpd.shutdown()


def _fields():
    fields = QgsFields()
    fields.append(QgsField("kumoy_id", QVariant.LongLong))
    fields.append(QgsField("integer_value", QVariant.LongLong))
    fields.append(QgsField("float_value", QVariant.Double))
    fields.append(QgsField("boolean_value", QVariant.Bool))
    fields.append(QgsField("string_value", QVariant.String))
    return fields


def _v2_rows():
    rows = [
        (1, 42, 3.25, True, "first", "POINT ZM (139 35 10 20)"),
        (2, None, 8.5, None, "partial", None),
        (
            3,
            9_007_199_254_740_991,
            -2.5,
            False,
            "日本語",
            "POINT ZM (140 36 -5 7)",
        ),
    ]
    return [
        {
            "kumoy_id": row[0],
            "kumoy_wkb": (
                base64.b64encode(QgsGeometry.fromWkt(row[5]).asWkb()).decode()
                if row[5] is not None
                else ""
            ),
            "properties": {
                "integer_value": row[1],
                "float_value": row[2],
                "boolean_value": row[3],
                "string_value": row[4],
            },
        }
        for row in rows
    ]


def _snapshot(path):
    layer = QgsVectorLayer(path, "cache", "ogr")
    assert layer.isValid()
    fields = [(field.name(), field.type()) for field in layer.fields()]
    features = []
    for feature in layer.getFeatures():
        geometry = feature.geometry()
        features.append(
            (
                feature.id(),
                tuple(feature[name] for name in layer.fields().names()),
                geometry.asWkt(15),
            )
        )
    del layer
    return fields, features


def _configure_client(monkeypatch, server):
    from plugin_dir.kumoy.api import client

    monkeypatch.setattr(
        client.api_config,
        "get_api_config",
        lambda: SimpleNamespace(SERVER_URL=server),
    )
    monkeypatch.setattr(client, "get_token", lambda: "test-token")


@pytest.mark.usefixtures("qgis_plugin_path")
class TestDownloadFlatGeobufV3:
    def test_downloads_real_fixture_from_mock_server(
        self, tmp_path, monkeypatch, fgb_server
    ):
        from plugin_dir.kumoy.api import qgis_vector

        _configure_client(monkeypatch, fgb_server)
        progress = []
        path = qgis_vector.get_features_v3(
            "vector-id",
            progress_callback=lambda received, total: progress.append(
                (received, total)
            ),
        )
        try:
            assert Path(path).read_bytes() == FIXTURE.read_bytes()
            assert progress == [(FIXTURE.stat().st_size, FIXTURE.stat().st_size)]
        finally:
            os.unlink(path)

    def test_v3_sync_matches_v2_fallback(self, tmp_path, monkeypatch, fgb_server):
        from plugin_dir.kumoy.local_cache import vector
        from plugin_dir.kumoy.local_cache.settings import delete_last_updated

        _Handler.v2_rows = _v2_rows()
        _configure_client(monkeypatch, fgb_server)
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        monkeypatch.setattr(vector, "_get_cache_dir", lambda: str(cache_dir))

        progress = []
        vector.sync_local_cache(
            "v3",
            _fields(),
            QgsWkbTypes.PointZM,
            progress_callback=progress.append,
            expected_feature_count=3,
        )
        vector.sync_local_cache(
            "fallback",
            _fields(),
            QgsWkbTypes.PointZM,
            expected_feature_count=3,
        )

        try:
            assert progress[-1] == 100
            assert _snapshot(str(cache_dir / "v3.gpkg")) == _snapshot(
                str(cache_dir / "fallback.gpkg")
            )
        finally:
            delete_last_updated("v3")
            delete_last_updated("fallback")
