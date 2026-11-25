"""kumoy.api.client のトークンリフレッシュ（401 → リフレッシュ → 再送）のテスト"""

import pytest


@pytest.fixture
def client(qgis_plugin_path, monkeypatch):
    from plugin_dir.kumoy.api import client
    from plugin_dir.kumoy.settings_manager import store_setting

    store_setting("session_token", "old_at")
    store_setting("refresh_token", "old_rt")

    # _send returns the token as the "reply" so the test can see which token was used
    client.sent = []

    def fake_send(method, url, token, data):
        client.sent.append(token)
        return token, 0

    monkeypatch.setattr(client, "_send", fake_send)
    monkeypatch.setattr(
        client, "_status_code", lambda reply: 401 if reply == "old_at" else 200
    )
    monkeypatch.setattr(client, "_process_response", lambda reply, err: reply)
    yield client
    store_setting("session_token", "")
    store_setting("refresh_token", "")


def _settings():
    from plugin_dir.kumoy.settings_manager import get_settings

    return get_settings()


def test_refreshes_and_retries_on_401(client, monkeypatch):
    forms = []

    def fake_post(path, fields):
        forms.append((path, fields))
        return 200, {"access_token": "new_at", "refresh_token": "new_rt"}

    monkeypatch.setattr(client, "_post_auth_form", fake_post)

    assert client.ApiClient.get("/user/me") == "new_at"
    assert client.sent == ["old_at", "new_at"]
    assert forms == [
        (
            "/oauth2/token",
            {
                "grant_type": "refresh_token",
                "refresh_token": "old_rt",
                "client_id": "kumoy-qgis",
            },
        )
    ]
    assert _settings().session_token == "new_at"
    assert _settings().refresh_token == "new_rt"


def test_rejected_refresh_returns_original_401(client, monkeypatch):
    monkeypatch.setattr(
        client,
        "_post_auth_form",
        lambda path, fields: (400, {"error": "invalid_grant"}),
    )

    assert client.ApiClient.get("/user/me") == "old_at"
    assert client.sent == ["old_at"]
    assert _settings().refresh_token == ""


def test_legacy_session_token_is_not_refreshed(client, monkeypatch):
    from plugin_dir.kumoy.settings_manager import store_setting

    store_setting("refresh_token", "")

    def fail(path, fields):
        raise AssertionError("must not refresh without a refresh token")

    monkeypatch.setattr(client, "_post_auth_form", fail)

    assert client.ApiClient.get("/user/me") == "old_at"


def test_uses_token_refreshed_by_another_thread(client, monkeypatch):
    from plugin_dir.kumoy.settings_manager import store_setting

    def fake_send(method, url, token, data):
        client.sent.append(token)
        # Another thread rotates the tokens while this request is in flight
        store_setting("session_token", "other_at")
        return token, 0

    def fail(path, fields):
        raise AssertionError("must not refresh twice (rotation would revoke tokens)")

    monkeypatch.setattr(client, "_send", fake_send)
    monkeypatch.setattr(client, "_post_auth_form", fail)

    assert client.ApiClient.get("/user/me") == "other_at"
    assert client.sent == ["old_at", "other_at"]
