import base64
import http.server
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QDate, QDateTime, QTime, QVariant


class _Handler(http.server.BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.requests.append(
            {
                "path": self.path,
                "content_type": self.headers.get("Content-Type"),
                "body": body,
            }
        )

        if "/fallback/" in self.path and self.path.endswith("-v2"):
            self._send_json(404, {"message": "Not Found", "error": "v2 unavailable"})
            return
        self._send_json(200, [])

    def _send_json(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


@pytest.fixture
def upload_server():
    _Handler.requests = []
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    yield f"http://{host}:{port}"
    httpd.shutdown()


def _configure_client(monkeypatch, server):
    from plugin_dir.kumoy.api import client

    monkeypatch.setattr(
        client.api_config,
        "get_api_config",
        lambda: SimpleNamespace(SERVER_URL=server),
    )
    monkeypatch.setattr(client, "get_token", lambda: "test-token")


def _add_feature():
    fields = QgsFields()
    fields.append(QgsField("kumoy_id", QVariant.LongLong))
    fields.append(QgsField("name", QVariant.String))
    fields.append(QgsField("enabled", QVariant.Bool))
    fields.append(QgsField("observed_at", QVariant.DateTime))
    feature = QgsFeature(fields)
    feature.setAttributes(
        [
            99,
            "sample",
            True,
            QDateTime(QDate(2026, 2, 4), QTime(10, 29, 41, 859)),
        ]
    )
    feature.setGeometry(QgsGeometry.fromWkt("POINT ZM (139 35 10 20)"))
    feature.setValid(True)
    return feature


def _open_body(tmp_path: Path, request, name):
    path = tmp_path / name
    path.write_bytes(request["body"])
    layer = QgsVectorLayer(str(path), "upload", "ogr")
    assert layer.isValid()
    return layer


@pytest.mark.usefixtures("qgis_plugin_path")
class TestUploadFlatGeobufV2:
    def test_add_features_posts_flatgeobuf(self, tmp_path, monkeypatch, upload_server):
        from plugin_dir.kumoy.api import qgis_vector

        _configure_client(monkeypatch, upload_server)
        qgis_vector.add_features("new", [_add_feature()])

        request = _Handler.requests[-1]
        assert request["path"].endswith("/_qgis/vector/new/add-features-v2")
        assert request["content_type"] == "application/octet-stream"
        layer = _open_body(tmp_path, request, "add.fgb")
        assert layer.fields().names() == ["name", "enabled", "observed_at"]
        output = next(layer.getFeatures())
        assert output["name"] == "sample"
        assert output["enabled"] is True
        assert output["observed_at"] == "2026-02-04T10:29:41.859"
        assert QgsWkbTypes.hasZ(output.geometry().wkbType())
        assert QgsWkbTypes.hasM(output.geometry().wkbType())
        del layer

    def test_geometry_update_posts_id_and_geometry(
        self, tmp_path, monkeypatch, upload_server
    ):
        from plugin_dir.kumoy.api import qgis_vector

        _configure_client(monkeypatch, upload_server)
        geometry = QgsGeometry.fromWkt("LINESTRING Z (139 35 1, 140 36 2)")
        qgis_vector.change_geometry_values(
            "new", [{"kumoy_id": 42, "geom": geometry.asWkb()}]
        )

        request = _Handler.requests[-1]
        assert request["path"].endswith("/_qgis/vector/new/change-geometry-values-v2")
        assert request["content_type"] == "application/octet-stream"
        layer = _open_body(tmp_path, request, "geometry.fgb")
        assert layer.fields().names() == ["kumoy_id"]
        output = next(layer.getFeatures())
        assert output["kumoy_id"] == 42
        assert (
            QgsWkbTypes.flatType(output.geometry().wkbType()) == QgsWkbTypes.LineString
        )
        assert QgsWkbTypes.hasZ(output.geometry().wkbType())
        del layer

    def test_404_falls_back_to_json_endpoints(self, monkeypatch, upload_server):
        from plugin_dir.kumoy.api import qgis_vector

        _configure_client(monkeypatch, upload_server)
        feature = _add_feature()
        geometry = QgsGeometry.fromWkt("POINT (140 36)")

        qgis_vector.add_features("fallback", [feature])
        qgis_vector.change_geometry_values(
            "fallback", [{"kumoy_id": 7, "geom": geometry.asWkb()}]
        )

        paths = [request["path"] for request in _Handler.requests]
        assert paths == [
            "/api/_qgis/vector/fallback/add-features-v2",
            "/api/_qgis/vector/fallback/add-features",
            "/api/_qgis/vector/fallback/change-geometry-values-v2",
            "/api/_qgis/vector/fallback/change-geometry-values",
        ]
        add_body = json.loads(_Handler.requests[1]["body"])
        assert "kumoy_id" not in add_body["features"][0]["properties"]
        assert base64.b64decode(add_body["features"][0]["kumoy_wkb"])
        geometry_body = json.loads(_Handler.requests[3]["body"])
        assert geometry_body["geometry_items"][0]["kumoy_id"] == 7
        assert base64.b64decode(
            geometry_body["geometry_items"][0]["kumoy_wkb"]
        ) == bytes(geometry.asWkb())

    def test_enforces_services_byte_limit(self, monkeypatch):
        from plugin_dir.kumoy.api import qgis_vector

        assert qgis_vector.constants.MAX_FLATGEOBUF_BYTES == 7_500_000
        monkeypatch.setattr(qgis_vector.constants, "MAX_FLATGEOBUF_BYTES", 3)
        monkeypatch.setattr(
            qgis_vector, "features_to_flatgeobuf", lambda *_a, **_k: b"1234"
        )

        with pytest.raises(qgis_vector.FlatGeobufTooLargeError, match="4 > 3 bytes"):
            qgis_vector.add_features("new", [_add_feature()])
