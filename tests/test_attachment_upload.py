"""Uploading a staged file: its name carries no type, so the bytes have to."""

import pytest

VECTOR_ID = "11111111-1111-4111-8111-111111111111"
COLUMN_ID = "22222222-2222-4222-8222-222222222222"
ATTACHMENT_ID = "aaaaaaaa-3333-4333-8333-333333333333"

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 32
WEBP = b"RIFF" + b"0000" + b"WEBP" + b"0" * 32


@pytest.mark.usefixtures("qgis_plugin_path")
class TestSniffContentType:
    @pytest.mark.parametrize(
        "data,expected",
        [(PNG, "image/png"), (JPEG, "image/jpeg"), (WEBP, "image/webp")],
    )
    def test_detects_the_supported_formats(self, tmp_path, data, expected):
        from plugin_dir.kumoy import attachment

        # No extension: this is how a staged file is named
        path = tmp_path / ATTACHMENT_ID
        path.write_bytes(data)

        assert attachment.sniff_content_type(str(path)) == expected

    def test_rejects_data_that_is_not_an_image(self, tmp_path):
        from plugin_dir.kumoy import attachment

        path = tmp_path / ATTACHMENT_ID
        path.write_bytes(b"not an image")

        with pytest.raises(attachment.UnsupportedAttachmentError) as e:
            attachment.sniff_content_type(str(path))
        # An empty message would surface as "Failed to upload attachment:"
        assert str(e.value) != ""


@pytest.mark.usefixtures("qgis_plugin_path")
class TestUploadStaged:
    def test_uploads_the_staged_file_with_the_id_already_in_the_column(
        self, tmp_path, monkeypatch
    ):
        from plugin_dir.kumoy import attachment, local_cache

        staged = tmp_path / ATTACHMENT_ID
        staged.write_bytes(PNG)
        seen = {}
        promoted = {}

        monkeypatch.setattr(
            local_cache.attachment,
            "get_staged_path",
            lambda vector_id, attachment_id: str(staged),
        )
        monkeypatch.setattr(
            local_cache.attachment,
            "promote_staged",
            lambda vector_id, attachment_id: promoted.update(id=attachment_id),
        )
        monkeypatch.setattr(
            local_cache.attachment, "store", lambda *a, **k: str(staged)
        )

        def fake_create(**kwargs):
            seen.update(kwargs)
            return attachment.api.attachment.AttachmentUpload(
                attachment_id=kwargs["attachment_id"]
            )

        monkeypatch.setattr(attachment.api.attachment, "create_attachment", fake_create)

        attachment.upload_staged(
            vector_id=VECTOR_ID,
            vector_column_id=COLUMN_ID,
            attachment_id=ATTACHMENT_ID,
        )

        assert seen["attachment_id"] == ATTACHMENT_ID
        # Derived from the bytes; the staged name has no extension to go by
        assert seen["content_type"] == "image/png"
        assert promoted == {"id": ATTACHMENT_ID}


@pytest.mark.usefixtures("qgis_plugin_path")
class TestValidate:
    def test_reports_a_missing_extension_readably(self, tmp_path):
        from plugin_dir.kumoy import attachment

        path = tmp_path / ATTACHMENT_ID
        path.write_bytes(PNG)

        with pytest.raises(attachment.UnsupportedAttachmentError) as e:
            attachment.validate(str(path))
        assert str(e.value) != ""
