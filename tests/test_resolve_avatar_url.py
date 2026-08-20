import pytest


@pytest.mark.usefixtures("qgis_plugin_path")
class TestResolveAvatarUrl:
    """resolve_avatar_url が外部URLと自前パスを正しく扱うことを検証する"""

    def _mod(self):
        from plugin_dir.kumoy.api import user

        return user

    def test_external_https_url_is_returned_as_is(self):
        url = "https://lh3.googleusercontent.com/a/abc123"
        assert self._mod().resolve_avatar_url(url) == url

    def test_external_http_url_is_returned_as_is(self):
        url = "http://example.com/avatar.png"
        assert self._mod().resolve_avatar_url(url) == url

    def test_relative_path_is_prefixed_with_server_url(self, monkeypatch):
        m = self._mod()
        monkeypatch.setattr(
            m.api_config,
            "get_api_config",
            lambda: m.api_config.ApiConfig(SERVER_URL="https://example.kumoy.io"),
        )
        assert (
            m.resolve_avatar_url("/user-content/avatars/a.png")
            == "https://example.kumoy.io/user-content/avatars/a.png"
        )

    def test_trailing_slash_in_server_url_does_not_duplicate(self, monkeypatch):
        m = self._mod()
        monkeypatch.setattr(
            m.api_config,
            "get_api_config",
            lambda: m.api_config.ApiConfig(SERVER_URL="https://example.kumoy.io/"),
        )
        assert (
            m.resolve_avatar_url("/user-content/avatars/a.png")
            == "https://example.kumoy.io/user-content/avatars/a.png"
        )
