"""Tests for kumoy/local_cache/attachment.py"""

import os
import types

import pytest

VECTOR_ID = "11111111-1111-4111-8111-111111111111"
ATTACHMENT_ID = "aaaaaaaa-2222-4222-8222-222222222222"


@pytest.mark.usefixtures("qgis_plugin_path")
class TestParseAttachmentId:
    def test_accepts_uuid(self):
        from plugin_dir.kumoy.local_cache import attachment

        assert attachment.parse_attachment_id(ATTACHMENT_ID) == ATTACHMENT_ID

    def test_normalizes_case(self):
        from plugin_dir.kumoy.local_cache import attachment

        assert attachment.parse_attachment_id(ATTACHMENT_ID.upper()) == ATTACHMENT_ID

    @pytest.mark.parametrize(
        "attachment_id",
        [
            "",
            "not-a-uuid",
            f"{ATTACHMENT_ID}.jpg",
            f"../../{ATTACHMENT_ID}",
            f"{ATTACHMENT_ID}/../../etc/passwd",
            f"/abs/{ATTACHMENT_ID}",
            None,
            123,
        ],
    )
    def test_rejects_anything_else(self, attachment_id):
        from plugin_dir.kumoy.local_cache import attachment

        assert attachment.parse_attachment_id(attachment_id) is None


@pytest.mark.usefixtures("qgis_plugin_path")
class TestCachePath:
    def test_rejects_invalid_attachment_id(self, tmp_path, monkeypatch):
        from plugin_dir.kumoy.local_cache import attachment

        monkeypatch.setattr(
            attachment, "_get_cache_dir", lambda vector_id: str(tmp_path)
        )
        with pytest.raises(attachment.InvalidAttachmentId):
            attachment.get_cache_path(VECTOR_ID, "../escape")

    def test_rejects_invalid_vector_id(self):
        from plugin_dir.kumoy.local_cache import attachment

        with pytest.raises(attachment.InvalidAttachmentId):
            attachment.get_cache_path("../../escape", ATTACHMENT_ID)

    def test_is_cached_is_false_for_invalid_id(self, tmp_path, monkeypatch):
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
        path = s.mod.sync_local_cache(VECTOR_ID, ATTACHMENT_ID)

        assert path == os.path.join(s.cache_dir, ATTACHMENT_ID)
        assert os.path.exists(path)
        assert s.calls == {"get_url": 1, "download": 1}
        assert not os.path.exists(path + ".part")

    def test_returns_cached_without_network(self, setup):
        s = setup
        cached = os.path.join(s.cache_dir, ATTACHMENT_ID)
        with open(cached, "wb") as f:
            f.write(b"CACHED")

        path = s.mod.sync_local_cache(VECTOR_ID, ATTACHMENT_ID)

        assert path == cached
        assert s.calls == {"get_url": 0, "download": 0}

    def test_store_copies_without_consuming_source(self, setup, tmp_path):
        s = setup
        src = tmp_path / "photo.jpg"
        src.write_bytes(b"SRC")

        path = s.mod.store(VECTOR_ID, ATTACHMENT_ID, str(src))

        assert open(path, "rb").read() == b"SRC"
        # The file the user picked must survive
        assert src.exists()
        assert not os.path.exists(path + ".part")


@pytest.mark.usefixtures("qgis_plugin_path")
class TestStaging:
    @pytest.fixture
    def setup(self, tmp_path, monkeypatch):
        from plugin_dir.kumoy.local_cache import attachment

        cache_dir = tmp_path / "attachments" / VECTOR_ID
        cache_dir.mkdir(parents=True)
        monkeypatch.setattr(
            attachment, "_get_cache_dir", lambda vector_id: str(cache_dir)
        )
        return types.SimpleNamespace(mod=attachment, cache_dir=cache_dir)

    def test_staging_copies_the_file_under_the_attachment_id(self, setup, tmp_path):
        s = setup
        src = tmp_path / "photo.JPG"
        src.write_bytes(b"SRC")

        staged = s.mod.stage(VECTOR_ID, ATTACHMENT_ID, str(src))

        assert s.mod.is_staged(VECTOR_ID, ATTACHMENT_ID)
        assert open(staged, "rb").read() == b"SRC"
        # The staged copy has to outlive the file the user picked
        src.unlink()
        assert os.path.exists(staged)

    def test_staged_is_not_reported_as_cached(self, setup, tmp_path):
        s = setup
        src = tmp_path / "photo.jpg"
        src.write_bytes(b"SRC")
        s.mod.stage(VECTOR_ID, ATTACHMENT_ID, str(src))

        # Not on the server yet, so it must not look like a downloaded file
        assert s.mod.is_cached(VECTOR_ID, ATTACHMENT_ID) is False

    def test_promote_moves_the_file_into_the_cache(self, setup, tmp_path):
        s = setup
        src = tmp_path / "photo.jpg"
        src.write_bytes(b"SRC")
        s.mod.stage(VECTOR_ID, ATTACHMENT_ID, str(src))

        s.mod.promote_staged(VECTOR_ID, ATTACHMENT_ID)

        assert s.mod.is_staged(VECTOR_ID, ATTACHMENT_ID) is False
        assert s.mod.is_cached(VECTOR_ID, ATTACHMENT_ID)
        assert (
            open(s.mod.get_cache_path(VECTOR_ID, ATTACHMENT_ID), "rb").read() == b"SRC"
        )

    def test_discard_removes_the_staged_file(self, setup, tmp_path):
        s = setup
        src = tmp_path / "photo.jpg"
        src.write_bytes(b"SRC")
        s.mod.stage(VECTOR_ID, ATTACHMENT_ID, str(src))

        s.mod.discard_staged(VECTOR_ID, ATTACHMENT_ID)

        assert s.mod.is_staged(VECTOR_ID, ATTACHMENT_ID) is False
        # Discarding twice is not an error: rollback may run after an upload
        s.mod.discard_staged(VECTOR_ID, ATTACHMENT_ID)

    def test_sync_returns_the_staged_file_without_network(self, setup, tmp_path):
        s = setup
        src = tmp_path / "photo.jpg"
        src.write_bytes(b"SRC")
        s.mod.stage(VECTOR_ID, ATTACHMENT_ID, str(src))

        assert s.mod.sync_local_cache(
            VECTOR_ID, ATTACHMENT_ID
        ) == s.mod.get_staged_path(VECTOR_ID, ATTACHMENT_ID)

    @pytest.mark.parametrize(
        "attachment_id",
        [
            "",
            None,
            123,
            "not-a-uuid",
            f"{ATTACHMENT_ID}.jpg",
            f"../{ATTACHMENT_ID}",
            f"{ATTACHMENT_ID}/../../etc/passwd",
        ],
    )
    def test_rejects_anything_that_is_not_an_attachment_id(self, setup, attachment_id):
        s = setup

        assert s.mod.is_staged(VECTOR_ID, attachment_id) is False
        with pytest.raises(s.mod.InvalidAttachmentId):
            s.mod.get_staged_path(VECTOR_ID, attachment_id)
