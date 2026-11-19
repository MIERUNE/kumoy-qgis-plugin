"""kumoy.api.client against a real local HTTP server.

The other tests mock the API layer, so these are the ones that exercise the
real QgsBlockingNetworkRequest / QgsNetworkReplyContent calls.
"""

import http.server
import json
import threading
from urllib.parse import parse_qs

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
        if self.path == "/api/needs-fresh":
            if self.headers.get("Authorization") == "Bearer fresh":
                self._reply(200, {"ok": True})
            else:
                self._reply(401, {"message": "Unauthorized"})
        elif self.path.startswith("/api/ok"):
            self._reply(200, {"path": self.path})
        elif self.path == "/api/forbidden":
            self._reply(403, {"message": "Forbidden", "error": "role"})
        else:
            self._reply(401, {"message": "Unauthorized", "error": "expired"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        if self.path == "/api/auth/oauth2/token":
            seen["content_type"] = self.headers.get("Content-Type")
            form = {k: v[0] for k, v in parse_qs(body.decode()).items()}
            seen.setdefault("refreshes", []).append(form)
            if form.get("refresh_token") == "rt-good":
                self._reply(200, {"access_token": "fresh", "refresh_token": "rt-next"})
            else:
                self._reply(400, {"error": "invalid_grant"})
            return
        self._reply(200, json.loads(body or b"{}"))

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
    monkeypatch.setattr(session, "_refresh_token", None)
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


def test_401_refreshes_once_and_retries(client, monkeypatch):
    from plugin_dir.kumoy import session

    monkeypatch.setattr(session, "_refresh_token", "rt-good")
    assert client.get("/needs-fresh") == {"ok": True}
    assert seen["content_type"] == "application/x-www-form-urlencoded"
    assert seen["refreshes"] == [
        {
            "grant_type": "refresh_token",
            "refresh_token": "rt-good",
            "client_id": "kumoy-qgis",
        }
    ]
    assert session.get_token() == "fresh"
    assert session.get_refresh_token() == "rt-next"


def test_rejected_refresh_reports_the_401(client, monkeypatch):
    from plugin_dir.kumoy import session
    from plugin_dir.kumoy.api.error import UnauthorizedError

    monkeypatch.setattr(session, "_refresh_token", "rt-revoked")
    with pytest.raises(UnauthorizedError) as e:
        client.get("/needs-fresh")
    # The 401 handler then logs out this login
    assert e.value.rejected_token == "tok"
    assert len(seen["refreshes"]) == 1


def test_login_before_oauth_does_not_refresh(client):
    from plugin_dir.kumoy.api.error import UnauthorizedError

    with pytest.raises(UnauthorizedError):
        client.get("/needs-fresh")
    assert "refreshes" not in seen


def test_refresh_skipped_when_the_login_changed(client, monkeypatch):
    from plugin_dir.kumoy import session

    # Another request refreshed while this one was in flight
    monkeypatch.setattr(session, "_refresh_token", "rt-used")
    assert client._refreshed_token("old") == "tok"
    assert "refreshes" not in seen


def test_session_reads_both_storage_formats(qgis_app):
    from plugin_dir.kumoy import session

    assert session._decode("legacy-session") == ("legacy-session", None)
    stored = json.dumps({"access_token": "a", "refresh_token": "r"})
    assert session._decode(stored) == ("a", "r")
