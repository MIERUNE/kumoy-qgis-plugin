"""kumoy/local_cache/attachment.py のテスト

添付は immutable なので「在れば即返す / 無ければダウンロード」だけを検証する。
属性値の形式検証は、想定外の文字列でキャッシュパスを組ませない（パストラバーサル
防止）ために重要なので厚めに見る。
"""

import os
import types

import pytest

VECTOR_ID = "11111111-1111-4111-8111-111111111111"
ATTACHMENT_ID = "aaaaaaaa-2222-4222-8222-222222222222"
VALUE = f"{ATTACHMENT_ID}.jpg"


@pytest.mark.usefixtures("qgis_plugin_path")
class TestParseValue:
    def test_accepts_uuid_dot_ext(self):
        from plugin_dir.kumoy.local_cache import attachment

        assert attachment.parse_value(VALUE) == (ATTACHMENT_ID, "jpg")

    def test_normalizes_case(self):
        from plugin_dir.kumoy.local_cache import attachment

        assert attachment.parse_value(f"{ATTACHMENT_ID.upper()}.JPG") == (
            ATTACHMENT_ID,
            "jpg",
        )

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "not-a-uuid.jpg",
            ATTACHMENT_ID,  # 拡張子なし
            f"../../{ATTACHMENT_ID}.jpg",
            f"{ATTACHMENT_ID}.jpg/../../etc/passwd",
            f"/abs/{ATTACHMENT_ID}.jpg",
            None,
            123,
        ],
    )
    def test_rejects_anything_else(self, value):
        from plugin_dir.kumoy.local_cache import attachment

        assert attachment.parse_value(value) is None


@pytest.mark.usefixtures("qgis_plugin_path")
class TestCachePath:
    def test_rejects_invalid_value(self, tmp_path, monkeypatch):
        from plugin_dir.kumoy.local_cache import attachment

        monkeypatch.setattr(
            attachment, "_get_cache_dir", lambda vector_id: str(tmp_path)
        )
        with pytest.raises(attachment.InvalidAttachmentValue):
            attachment.get_cache_path(VECTOR_ID, "../escape.jpg")

    def test_rejects_invalid_vector_id(self):
        from plugin_dir.kumoy.local_cache import attachment

        with pytest.raises(attachment.InvalidAttachmentValue):
            attachment.get_cache_path("../../escape", VALUE)

    def test_is_cached_is_false_for_invalid_value(self, tmp_path, monkeypatch):
        from plugin_dir.kumoy.local_cache import attachment

        monkeypatch.setattr(
            attachment, "_get_cache_dir", lambda vector_id: str(tmp_path)
        )
        assert attachment.is_cached(VECTOR_ID, "nonsense") is False


@pytest.mark.usefixtures("qgis_plugin_path")
class TestSyncLocalCache:
    @pytest.fixture
    def setup(self, tmp_path, monkeypatch):
        from plugin_dir.kumoy.local_cache import attachment

        cache_dir = tmp_path / "attachments" / VECTOR_ID
        cache_dir.mkdir(parents=True)
        monkeypatch.setattr(
            attachment, "_get_cache_dir", lambda vector_id: str(cache_dir)
        )

        calls = {"get_url": 0, "download": 0}

        def fake_download(url, dest_path, progress_callback=None, is_canceled=None):
            calls["download"] += 1
            with open(dest_path, "wb") as f:
                f.write(b"JPEG-BYTES")

        def fake_get_download_url(vector_id, attachment_id):
            calls["get_url"] += 1
            return f"https://s3/{vector_id}/{attachment_id}?sig=x"

        monkeypatch.setattr(
            attachment,
            "api",
            types.SimpleNamespace(
                attachment=types.SimpleNamespace(get_download_url=fake_get_download_url)
            ),
        )
        monkeypatch.setattr(attachment.download, "download_to_file", fake_download)

        yield types.SimpleNamespace(
            mod=attachment, cache_dir=str(cache_dir), calls=calls
        )

    def test_downloads_when_missing(self, setup):
        s = setup
        path = s.mod.sync_local_cache(VECTOR_ID, VALUE)

        # 拡張子を保つのが重要（QGIS 側が形式を判定できるようにする）
        assert path == os.path.join(s.cache_dir, VALUE)
        assert os.path.exists(path)
        assert s.calls == {"get_url": 1, "download": 1}
        # 完成ファイルだけが残り、.part は消えている
        assert not os.path.exists(path + ".part")

    def test_returns_cached_without_network(self, setup):
        s = setup
        cached = os.path.join(s.cache_dir, VALUE)
        with open(cached, "wb") as f:
            f.write(b"CACHED")

        path = s.mod.sync_local_cache(VECTOR_ID, VALUE)

        assert path == cached
        assert s.calls == {"get_url": 0, "download": 0}

    def test_store_copies_without_consuming_source(self, setup, tmp_path):
        s = setup
        src = tmp_path / "photo.jpg"
        src.write_bytes(b"SRC")

        path = s.mod.store(VECTOR_ID, VALUE, str(src))

        assert open(path, "rb").read() == b"SRC"
        # ユーザーが選んだ元ファイルは消さない
        assert src.exists()
        assert not os.path.exists(path + ".part")
