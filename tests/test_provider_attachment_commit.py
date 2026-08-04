"""Attachments are uploaded when the layer edits are committed, not when picked.

The widget only stages the file, so if the provider drops the staged reference
the feature silently ends up with no attachment — or with the reference itself
written into the column.
"""

import types

import pytest

VECTOR_ID = "11111111-1111-4111-8111-111111111111"
COLUMN_ID = "22222222-2222-4222-8222-222222222222"
ATTACHMENT_ID = "aaaaaaaa-3333-4333-8333-333333333333"
OTHER_ATTACHMENT_ID = "bbbbbbbb-3333-4333-8333-333333333333"


@pytest.fixture
def provider(qgis_plugin_path, monkeypatch):
    """A stand-in carrying the real commit methods, with the API stubbed out."""
    from qgis.core import QgsField, QgsFields, QgsWkbTypes
    from qgis.PyQt.QtCore import QVariant

    from plugin_dir.kumoy import api, attachment, local_cache
    from plugin_dir.kumoy.provider.dataprovider import KumoyDataProvider

    fields = QgsFields()
    fields.append(QgsField("kumoy_id", QVariant.LongLong))
    fields.append(QgsField("photo", QVariant.String))
    fields.append(QgsField("name", QVariant.String))

    calls = types.SimpleNamespace(added=[], changed=[], uploads=[], errors=[])

    def fake_add_features(vector_id, features):
        calls.added.append(
            [dict(zip(f.fields().names(), f.attributes())) for f in features]
        )
        return [101 + i for i in range(len(features))]

    def fake_change_attribute_values(vector_id, attribute_items):
        calls.changed.append(attribute_items)

    def fake_upload_staged(vector_id, vector_column_id, attachment_id, **kwargs):
        calls.uploads.append(
            {
                "vector_id": vector_id,
                "vector_column_id": vector_column_id,
                "attachment_id": attachment_id,
            }
        )
        if calls.upload_error is not None:
            raise calls.upload_error

    # A value is staged until its file has been uploaded
    calls.staged = {ATTACHMENT_ID, OTHER_ATTACHMENT_ID}
    calls.upload_error = None
    monkeypatch.setattr(
        local_cache.attachment,
        "is_staged",
        lambda vector_id, attachment_id: attachment_id in calls.staged,
    )
    monkeypatch.setattr(api.qgis_vector, "add_features", fake_add_features)
    monkeypatch.setattr(
        api.qgis_vector, "change_attribute_values", fake_change_attribute_values
    )
    monkeypatch.setattr(attachment, "upload_staged", fake_upload_staged)

    class _Provider:
        _attachment_column_ids = KumoyDataProvider._attachment_column_ids
        _upload_staged_attachments = KumoyDataProvider._upload_staged_attachments
        _attachment_values = KumoyDataProvider._attachment_values
        _report_attachment_error = KumoyDataProvider._report_attachment_error
        addFeatures = KumoyDataProvider.addFeatures
        changeAttributeValues = KumoyDataProvider.changeAttributeValues

        kumoy_vector = types.SimpleNamespace(
            id=VECTOR_ID,
            columns=[
                {"id": COLUMN_ID, "name": "photo", "type": "attachment"},
                {"id": "col-name", "name": "name", "type": "string"},
            ],
        )

        def fields(self):
            return fields

        def wkbType(self):
            return QgsWkbTypes.Point

        def _reload_vector(self):
            pass

        def pushError(self, message):
            calls.errors.append(message)

    instance = _Provider()
    instance.calls = calls
    return instance


def _feature(fields, photo=None):
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY

    feature = QgsFeature(fields)
    feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(0, 0)))
    feature["name"] = "a"
    if photo is not None:
        feature["photo"] = photo
    return feature


class TestChangeAttributeValues:
    def test_uploads_the_staged_file_and_keeps_the_value(self, provider):
        assert provider.changeAttributeValues({7: {1: ATTACHMENT_ID}}) is True

        assert provider.calls.uploads == [
            {
                "vector_id": VECTOR_ID,
                "vector_column_id": COLUMN_ID,
                "attachment_id": ATTACHMENT_ID,
            }
        ]
        # The widget already wrote the final value, so the upload does not change it
        assert provider.calls.changed == [
            [{"kumoy_id": 7, "properties": {"photo": ATTACHMENT_ID}}]
        ]

    def test_leaves_an_already_uploaded_value_alone(self, provider):
        provider.calls.staged.clear()

        assert provider.changeAttributeValues({7: {1: ATTACHMENT_ID}}) is True

        assert provider.calls.uploads == []
        assert provider.calls.changed == [
            [{"kumoy_id": 7, "properties": {"photo": ATTACHMENT_ID}}]
        ]

    def test_fails_the_commit_when_the_upload_fails(self, provider):
        provider.calls.upload_error = RuntimeError("boom")

        assert provider.changeAttributeValues({7: {1: ATTACHMENT_ID, 2: "a"}}) is False
        # Nothing had been sent yet, so the edits stay in the buffer
        assert provider.calls.changed == []
        assert provider.calls.errors != []


class TestAddFeatures:
    def test_uploads_before_the_insert_and_keeps_the_value(self, provider):
        feature = _feature(provider.fields(), photo=ATTACHMENT_ID)

        ok, added = provider.addFeatures([feature])

        assert ok is True and len(added) == 1
        assert provider.calls.uploads == [
            {
                "vector_id": VECTOR_ID,
                "vector_column_id": COLUMN_ID,
                "attachment_id": ATTACHMENT_ID,
            }
        ]
        # 1リクエストで入る。採番後に属性を書き直す往復は要らない
        assert provider.calls.added[0][0]["photo"] == ATTACHMENT_ID
        assert provider.calls.changed == []

    def test_uploads_the_file_staged_for_each_feature(self, provider):
        features = [
            _feature(provider.fields(), photo=ATTACHMENT_ID),
            _feature(provider.fields()),
            _feature(provider.fields(), photo=OTHER_ATTACHMENT_ID),
        ]

        assert provider.addFeatures(features)[0] is True

        assert [u["attachment_id"] for u in provider.calls.uploads] == [
            ATTACHMENT_ID,
            OTHER_ATTACHMENT_ID,
        ]

    def test_uploads_nothing_when_no_file_was_staged(self, provider):
        assert provider.addFeatures([_feature(provider.fields())])[0] is True

        assert provider.calls.uploads == []
        assert provider.calls.changed == []

    def test_sends_a_value_whose_file_is_already_uploaded_as_is(self, provider):
        # 添付を持つ地物の複製など。重複参照はサーバーが拒否するので黙って捨てない
        provider.calls.staged.clear()
        feature = _feature(provider.fields(), photo=ATTACHMENT_ID)

        assert provider.addFeatures([feature])[0] is True

        assert provider.calls.uploads == []
        assert provider.calls.added[0][0]["photo"] == ATTACHMENT_ID

    def test_fails_the_commit_when_the_upload_fails(self, provider):
        provider.calls.upload_error = RuntimeError("boom")
        feature = _feature(provider.fields(), photo=ATTACHMENT_ID)

        ok, added = provider.addFeatures([feature])

        # まだ何も送っていないので、編集はバッファに残す
        assert ok is False and added == []
        assert provider.calls.added == []
        assert provider.calls.errors != []
