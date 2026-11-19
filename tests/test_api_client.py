"""kumoy.api.client against a real local HTTP server.

The other tests mock the API layer, so these are the ones that exercise the
real QgsBlockingNetworkRequest / QgsNetworkReplyContent calls.
"""

import http.server
import json
import threading

import pytest

seen = {}


class _Handler(http.server.BaseHTTPRequestHandler):
    def _reply(self, status, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        seen["authorization"] = self.headers.get("Authorization")
        if self.path.startswith("/api/ok"):
            self._reply(200, {"path": self.path})
        elif self.path == "/api/forbidden":
            self._reply(403, {"message": "Forbidden", "error": "role"})
        else:
            self._reply(401, {"message": "Unauthorized", "error": "expired"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self._reply(200, json.loads(self.rfile.read(length) or b"{}"))

    def log_message(self, *args):
        pass


@pytest.fixture
def client(qgis_app, monkeypatch):
    from plugin_dir.kumoy import session
    from plugin_dir.kumoy.api import client

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    host, port = httpd.server_address
    monkeypatch.setattr(client, "server_url", lambda: f"http://{host}:{port}")
    monkeypatch.setattr(session, "_token", "tok")
    seen.clear()
    yield client
    httpd.shutdown()


def test_get_json_auth_and_params(client):
    assert client.get("/ok", params={"q": "a b"}) == {"path": "/api/ok?q=a+b"}
    assert seen["authorization"] == "Bearer tok"


def test_post_sends_json(client):
    assert client.post("/echo", {"name": "日本"}) == {"name": "日本"}


def test_response_headers_are_returned(client):
    headers = {}
    client.request("GET", "/api/ok", response_headers=headers)
    assert headers["content-type"] == "application/json"
    assert "date" in headers  # used as the server clock by the vector sync


def test_status_maps_to_typed_errors(client):
    from plugin_dir.kumoy.api.error import ForbiddenError, UnauthorizedError

    with pytest.raises(ForbiddenError) as e:
        client.get("/forbidden")
    assert e.value.error == "role"
    with pytest.raises(UnauthorizedError) as e:
        client.get("/other")
    # The 401 handler compares it with the current login
    assert e.value.rejected_token == "tok"


def test_network_error(client, monkeypatch):
    from plugin_dir.kumoy.api.error import NetworkError

    # Nothing listens on port 1
    monkeypatch.setattr(client, "server_url", lambda: "http://127.0.0.1:1")
    with pytest.raises(NetworkError):
        client.get("/ok")
