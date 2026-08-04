"""Tests for kumoy/external_storage.py"""

import re
import types

import pytest

VECTOR_ID = "11111111-1111-4111-8111-111111111111"
COLUMN_ID = "22222222-2222-4222-8222-222222222222"
ATTACHMENT_ID = "aaaaaaaa-3333-4333-8333-333333333333"


@pytest.mark.usefixtures("qgis_plugin_path")
class TestStorageUrl:
    def test_expression_is_constant(self):
        from plugin_dir.kumoy import external_storage

        expr = external_storage.build_storage_url_expression(VECTOR_ID, COLUMN_ID)

        assert expr == f"'kumoy://{VECTOR_ID}/{COLUMN_ID}'"

    def test_parses_url(self):
        from plugin_dir.kumoy import external_storage

        url = f"kumoy://{VECTOR_ID}/{COLUMN_ID}"
        assert external_storage.parse_storage_url(url) == (VECTOR_ID, COLUMN_ID)

    def test_still_parses_the_kumoy_id_suffix_saved_by_older_projects(self):
        from plugin_dir.kumoy import external_storage

        url = f"kumoy://{VECTOR_ID}/{COLUMN_ID}/42"
        assert external_storage.parse_storage_url(url) == (VECTOR_ID, COLUMN_ID)

    @pytest.mark.parametrize(
        "url",
        [
            "",
            f"'kumoy://{VECTOR_ID}/{COLUMN_ID}'",
            f"kumoy://{VECTOR_ID}/{COLUMN_ID}/",
            f"kumoy://{VECTOR_ID}/{COLUMN_ID}/NULL",
            f"http://{VECTOR_ID}/{COLUMN_ID}",
        ],
    )
    def test_rejects_unresolved_or_foreign_urls(self, url):
        from plugin_dir.kumoy import external_storage

        assert external_storage.parse_storage_url(url) is None


@pytest.mark.usefixtures("qgis_plugin_path")
class TestFetchUrl:
    def test_parses_default_root_prefixed_attachment_id(self):
        from plugin_dir.kumoy import external_storage

        assert external_storage.parse_fetch_url(f"{VECTOR_ID}/{ATTACHMENT_ID}") == (
            VECTOR_ID,
            ATTACHMENT_ID,
        )

    @pytest.mark.parametrize(
        "url", ["", ATTACHMENT_ID, f"/{ATTACHMENT_ID}", f"a/b/{ATTACHMENT_ID}"]
    )
    def test_rejects_other_shapes(self, url):
        from plugin_dir.kumoy import external_storage

        assert external_storage.parse_fetch_url(url) is None


def local_cache_uuid(content) -> str:
    """The id doStore generated, checked to be a uuid rather than pinned."""
    value = content.url()
    assert re.match(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", value
    ), value
    return value


@pytest.mark.usefixtures("qgis_plugin_path")
class TestStoredContent:
    @pytest.fixture
    def staged(self, monkeypatch):
        from plugin_dir.kumoy import external_storage

        seen = {}

        def fake_stage(vector_id, attachment_id, src_path):
            seen.update(
                vector_id=vector_id, attachment_id=attachment_id, src_path=src_path
            )
            return f"/cache/{vector_id}/staged/{attachment_id}"

        monkeypatch.setattr(
            external_storage,
            "local_cache",
            types.SimpleNamespace(attachment=types.SimpleNamespace(stage=fake_stage)),
        )
        return seen

    def _fake_domain(self, monkeypatch, validate):
        from plugin_dir.kumoy import external_storage

        class Unsupported(Exception):
            pass

        class TooLarge(Exception):
            pass

        monkeypatch.setattr(
            external_storage,
            "attachment_domain",
            types.SimpleNamespace(
                validate=validate,
                UnsupportedAttachmentError=Unsupported,
                AttachmentTooLargeError=TooLarge,
                MAX_ATTACHMENT_BYTES=20 * 1024 * 1024,
            ),
        )
        return Unsupported, TooLarge

    def test_stages_the_file_without_uploading(self, monkeypatch, staged):
        from plugin_dir.kumoy import external_storage

        self._fake_domain(monkeypatch, lambda file_path: "image/jpeg")

        content = external_storage._StoredContent(
            "/tmp/photo.jpg", f"kumoy://{VECTOR_ID}/{COLUMN_ID}"
        )
        content.store()

        # The widget decides the id, so the value never changes on upload
        assert content.url() == local_cache_uuid(content)
        assert staged == {
            "vector_id": VECTOR_ID,
            "attachment_id": content.url(),
            "src_path": "/tmp/photo.jpg",
        }

    def test_works_for_a_feature_that_has_no_kumoy_id_yet(self, monkeypatch, staged):
        from plugin_dir.kumoy import external_storage

        self._fake_domain(monkeypatch, lambda file_path: "image/jpeg")

        # The storage url no longer carries kumoy_id, so nothing is unresolved
        content = external_storage._StoredContent(
            "/tmp/photo.jpg",
            external_storage.build_storage_url_expression(VECTOR_ID, COLUMN_ID).strip(
                "'"
            ),
        )
        content.store()

        assert content.url() == local_cache_uuid(content)
        assert content.errorString() == ""

    def test_rejects_an_unsupported_file_before_staging(self, monkeypatch, staged):
        from plugin_dir.kumoy import external_storage

        unsupported, _ = self._fake_domain(monkeypatch, lambda file_path: None)

        def reject(file_path):
            raise unsupported("gif")

        external_storage.attachment_domain.validate = reject

        content = external_storage._StoredContent(
            "/tmp/photo.gif", f"kumoy://{VECTOR_ID}/{COLUMN_ID}"
        )
        content.store()

        assert staged == {}
        assert content.url() == ""
        assert content.errorString() != ""

    def test_fails_on_a_malformed_storage_url(self):
        from plugin_dir.kumoy import external_storage

        content = external_storage._StoredContent("/tmp/photo.jpg", "kumoy://nonsense")
        content.store()

        assert content.url() == ""
        assert content.errorString() != ""


@pytest.mark.usefixtures("qgis_plugin_path")
class TestFetchedContent:
    def test_returns_cached_path_without_network(self, monkeypatch):
        from plugin_dir.kumoy import external_storage

        calls = {"sync": 0}
        monkeypatch.setattr(
            external_storage,
            "local_cache",
            types.SimpleNamespace(
                attachment=types.SimpleNamespace(
                    is_staged=lambda vector_id, attachment_id: False,
                    is_cached=lambda vector_id, attachment_id: True,
                    get_cache_path=lambda vector_id, attachment_id: (
                        f"/cache/{vector_id}/{attachment_id}"
                    ),
                    sync_local_cache=lambda *a, **k: calls.__setitem__(
                        "sync", calls["sync"] + 1
                    ),
                )
            ),
        )

        content = external_storage._FetchedContent(f"{VECTOR_ID}/{ATTACHMENT_ID}")
        content.fetch()

        assert content.filePath() == f"/cache/{VECTOR_ID}/{ATTACHMENT_ID}"
        assert calls["sync"] == 0

    def test_downloads_when_not_cached(self, monkeypatch):
        from plugin_dir.kumoy import external_storage

        monkeypatch.setattr(
            external_storage,
            "local_cache",
            types.SimpleNamespace(
                attachment=types.SimpleNamespace(
                    is_staged=lambda vector_id, attachment_id: False,
                    is_cached=lambda vector_id, attachment_id: False,
                    get_cache_path=lambda vector_id, attachment_id: "",
                    sync_local_cache=lambda vector_id, attachment_id, progress_callback=None, is_canceled=None: (
                        f"/downloaded/{vector_id}/{attachment_id}"
                    ),
                )
            ),
        )

        content = external_storage._FetchedContent(f"{VECTOR_ID}/{ATTACHMENT_ID}")
        content.fetch()

        assert content.filePath() == f"/downloaded/{VECTOR_ID}/{ATTACHMENT_ID}"

    def test_returns_the_staged_path_when_not_uploaded_yet(self, monkeypatch):
        from plugin_dir.kumoy import external_storage

        calls = {"is_cached": 0}
        monkeypatch.setattr(
            external_storage,
            "local_cache",
            types.SimpleNamespace(
                attachment=types.SimpleNamespace(
                    is_staged=lambda vector_id, attachment_id: True,
                    get_staged_path=lambda vector_id, attachment_id: (
                        f"/cache/{vector_id}/staged/{attachment_id}"
                    ),
                    is_cached=lambda *a, **k: calls.__setitem__(
                        "is_cached", calls["is_cached"] + 1
                    ),
                )
            ),
        )

        content = external_storage._FetchedContent(f"{VECTOR_ID}/{ATTACHMENT_ID}")
        content.fetch()

        # Nothing to download, and the cache must not be consulted for it
        assert content.filePath() == f"/cache/{VECTOR_ID}/staged/{ATTACHMENT_ID}"
        assert calls["is_cached"] == 0

    def test_fails_on_malformed_reference(self):
        from plugin_dir.kumoy import external_storage

        content = external_storage._FetchedContent(ATTACHMENT_ID)
        content.fetch()

        assert content.filePath() == ""
        assert content.errorString() != ""
