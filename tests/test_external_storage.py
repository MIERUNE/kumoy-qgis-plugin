"""kumoy/external_storage.py のテスト

QGIS 標準の Attachment ウィジェットとの接点なので、URL の組み立て／分解と
``doStore`` / ``doFetch`` の分岐を検証する。ウィジェット本体との結線は
実 GUI がないと再現できないため、ここでは URL 契約の側を固定する。
"""

import types

import pytest

VECTOR_ID = "11111111-1111-4111-8111-111111111111"
COLUMN_ID = "22222222-2222-4222-8222-222222222222"
ATTACHMENT_ID = "aaaaaaaa-3333-4333-8333-333333333333"
VALUE = f"{ATTACHMENT_ID}.jpg"


@pytest.mark.usefixtures("qgis_plugin_path")
class TestStorageUrl:
    def test_expression_keeps_kumoy_id_unevaluated(self):
        from plugin_dir.kumoy import external_storage

        expr = external_storage.build_storage_url_expression(VECTOR_ID, COLUMN_ID)

        # kumoy_id は地物ごとにウィジェット側で評価されるので式のまま残す
        assert expr == f"'kumoy://{VECTOR_ID}/{COLUMN_ID}/' || \"kumoy_id\""

    def test_parses_evaluated_url(self):
        from plugin_dir.kumoy import external_storage

        url = f"kumoy://{VECTOR_ID}/{COLUMN_ID}/42"
        assert external_storage.parse_storage_url(url) == (VECTOR_ID, COLUMN_ID, 42)

    @pytest.mark.parametrize(
        "url",
        [
            "",
            # 新規地物では kumoy_id が未採番なので式が解決されずここに来る
            f"'kumoy://{VECTOR_ID}/{COLUMN_ID}/' || \"kumoy_id\"",
            f"kumoy://{VECTOR_ID}/{COLUMN_ID}/",
            f"kumoy://{VECTOR_ID}/{COLUMN_ID}/NULL",
            f"http://{VECTOR_ID}/{COLUMN_ID}/1",
        ],
    )
    def test_rejects_unresolved_or_foreign_urls(self, url):
        from plugin_dir.kumoy import external_storage

        assert external_storage.parse_storage_url(url) is None


@pytest.mark.usefixtures("qgis_plugin_path")
class TestFetchUrl:
    def test_parses_default_root_prefixed_value(self):
        from plugin_dir.kumoy import external_storage

        assert external_storage.parse_fetch_url(f"{VECTOR_ID}/{VALUE}") == (
            VECTOR_ID,
            VALUE,
        )

    @pytest.mark.parametrize("url", ["", VALUE, f"/{VALUE}", f"a/b/{VALUE}"])
    def test_rejects_other_shapes(self, url):
        from plugin_dir.kumoy import external_storage

        assert external_storage.parse_fetch_url(url) is None


@pytest.mark.usefixtures("qgis_plugin_path")
class TestStoredContent:
    def test_uploads_and_exposes_value_as_url(self, monkeypatch):
        from plugin_dir.kumoy import external_storage

        seen = {}

        def fake_upload(
            vector_id,
            kumoy_id,
            vector_column_id,
            file_path,
            progress_callback=None,
            is_canceled=None,
        ):
            seen.update(
                vector_id=vector_id,
                kumoy_id=kumoy_id,
                vector_column_id=vector_column_id,
                file_path=file_path,
            )
            return VALUE

        monkeypatch.setattr(
            external_storage,
            "attachment_domain",
            types.SimpleNamespace(
                upload=fake_upload,
                UnsupportedAttachmentError=Exception,
                AttachmentTooLargeError=Exception,
                MAX_ATTACHMENT_BYTES=20 * 1024 * 1024,
            ),
        )

        content = external_storage._StoredContent(
            "/tmp/photo.jpg", f"kumoy://{VECTOR_ID}/{COLUMN_ID}/42"
        )
        content.store()

        assert seen == {
            "vector_id": VECTOR_ID,
            "kumoy_id": 42,
            "vector_column_id": COLUMN_ID,
            "file_path": "/tmp/photo.jpg",
        }
        # ウィジェットは url() を属性値として書き込むので、そのまま値でなければならない
        assert content.url() == VALUE

    def test_fails_when_feature_is_not_saved_yet(self):
        from plugin_dir.kumoy import external_storage

        # kumoy_id が未採番だと式が解決されず、生の式文字列が渡ってくる
        content = external_storage._StoredContent(
            "/tmp/photo.jpg", f"'kumoy://{VECTOR_ID}/{COLUMN_ID}/' || \"kumoy_id\""
        )
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
                    is_cached=lambda vector_id, value: True,
                    get_cache_path=lambda vector_id, value: (
                        f"/cache/{vector_id}/{value}"
                    ),
                    sync_local_cache=lambda *a, **k: calls.__setitem__(
                        "sync", calls["sync"] + 1
                    ),
                )
            ),
        )

        content = external_storage._FetchedContent(f"{VECTOR_ID}/{VALUE}")
        content.fetch()

        assert content.filePath() == f"/cache/{VECTOR_ID}/{VALUE}"
        assert calls["sync"] == 0

    def test_downloads_when_not_cached(self, monkeypatch):
        from plugin_dir.kumoy import external_storage

        monkeypatch.setattr(
            external_storage,
            "local_cache",
            types.SimpleNamespace(
                attachment=types.SimpleNamespace(
                    is_cached=lambda vector_id, value: False,
                    get_cache_path=lambda vector_id, value: "",
                    sync_local_cache=lambda vector_id, value, progress_callback=None, is_canceled=None: (
                        f"/downloaded/{vector_id}/{value}"
                    ),
                )
            ),
        )

        content = external_storage._FetchedContent(f"{VECTOR_ID}/{VALUE}")
        content.fetch()

        assert content.filePath() == f"/downloaded/{VECTOR_ID}/{VALUE}"

    def test_fails_on_malformed_reference(self):
        from plugin_dir.kumoy import external_storage

        content = external_storage._FetchedContent(VALUE)
        content.fetch()

        assert content.filePath() == ""
        assert content.errorString() != ""
