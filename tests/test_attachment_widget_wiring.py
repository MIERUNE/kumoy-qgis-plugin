"""End-to-end check that our widget config and QgsExternalStorage actually mesh.

Breakage here is silent: no preview, or picked files never reach the commit.
"""

import types

import pytest

VECTOR_ID = "11111111-1111-4111-8111-111111111111"
COLUMN_ID = "22222222-2222-4222-8222-222222222222"
NAME_COLUMN_ID = "99999999-9999-4999-8999-999999999999"
ATTACHMENT_ID = "aaaaaaaa-3333-4333-8333-333333333333"


@pytest.mark.usefixtures("qgis_plugin_path")
class TestAttachmentWidgetWiring:
    @pytest.fixture
    def setup(self, tmp_path, monkeypatch):
        from qgis.core import (
            QgsApplication,
            QgsFeature,
            QgsGeometry,
            QgsPointXY,
            QgsVectorLayer,
        )
        from qgis.gui import QgsGui

        from plugin_dir.kumoy import attachment as attachment_domain
        from plugin_dir.kumoy import external_storage, local_cache
        from plugin_dir.ui.layers.configure import configure_kumoy_layer

        QgsGui.editorWidgetRegistry().initEditors()

        uploaded = []
        monkeypatch.setattr(
            attachment_domain,
            "upload",
            lambda *a, **k: uploaded.append(k) or ATTACHMENT_ID,
        )

        # Staging is real, so the value the widget writes is a real pending ref
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        monkeypatch.setattr(
            local_cache.attachment, "_get_cache_dir", lambda vector_id: str(cache_dir)
        )

        cached_image = tmp_path / "cached.jpg"
        cached_image.write_bytes(b"IMG")
        fetched = {}
        monkeypatch.setattr(
            local_cache.attachment,
            "is_cached",
            lambda vector_id, attachment_id: (
                fetched.update(vector_id=vector_id, attachment_id=attachment_id) or True
            ),
        )
        monkeypatch.setattr(
            local_cache.attachment,
            "get_cache_path",
            lambda vector_id, attachment_id: str(cached_image),
        )

        external_storage.register()

        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326"
            "&field=kumoy_id:integer&field=name:string(255)&field=photo:string(255)",
            "t",
            "memory",
        )
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(0, 0)))
        feature["kumoy_id"] = 42
        layer.dataProvider().addFeatures([feature])
        feature = next(layer.getFeatures())

        vector = types.SimpleNamespace(
            id=VECTOR_ID,
            columns=[
                {"id": NAME_COLUMN_ID, "name": "name", "type": "string"},
                {"id": COLUMN_ID, "name": "photo", "type": "attachment"},
            ],
        )
        configure_kumoy_layer(layer, vector)

        yield types.SimpleNamespace(
            layer=layer,
            cache_dir=cache_dir,
            feature=feature,
            uploaded=uploaded,
            fetched=fetched,
            registry=QgsGui.editorWidgetRegistry(),
            external_storage=external_storage,
            app=QgsApplication,
        )

        external_storage.unregister()

    def _wrapper(self, s, feature=None):
        from qgis.PyQt.QtWidgets import QWidget

        idx = s.layer.fields().indexOf("photo")
        setup = s.layer.editorWidgetSetup(idx)
        # The parent must outlive the wrapper, or the wrapper is deleted
        s.parent = QWidget()
        wrapper = s.registry.create(
            "ExternalResource", s.layer, idx, setup.config(), None, s.parent
        )
        wrapper.setFeature(s.feature if feature is None else feature)
        return wrapper

    def test_only_attachment_columns_get_the_widget(self, setup):
        s = setup
        photo_idx = s.layer.fields().indexOf("photo")
        name_idx = s.layer.fields().indexOf("name")

        assert s.layer.editorWidgetSetup(photo_idx).type() == "ExternalResource"
        assert s.layer.editorWidgetSetup(name_idx).type() != "ExternalResource"

    def test_kumoy_id_is_read_only(self, setup):
        s = setup
        idx = s.layer.fields().indexOf("kumoy_id")
        assert s.layer.editFormConfig().readOnly(idx)

    def test_widget_is_bound_to_kumoy_storage(self, setup):
        wrapper = self._wrapper(setup)
        assert wrapper.widget().fileWidget().storageType() == "kumoy"

    def test_showing_a_value_resolves_through_the_local_cache(self, setup):
        s = setup
        wrapper = self._wrapper(s)

        wrapper.setValues(ATTACHMENT_ID, [])

        # DefaultRoot supplies the vector_id the stored id lacks
        assert s.fetched == {"vector_id": VECTOR_ID, "attachment_id": ATTACHMENT_ID}

    def test_selecting_a_file_stages_it_instead_of_uploading(self, setup, tmp_path):
        from plugin_dir.kumoy import local_cache

        s = setup
        wrapper = self._wrapper(s)
        picked = tmp_path / "picked.jpg"
        picked.write_bytes(b"x")

        wrapper.widget().fileWidget().setSelectedFileNames([str(picked)])

        # Upload is the provider's job at commit time, not the widget's
        assert s.uploaded == []
        # The value is already the final attachment id
        assert local_cache.attachment.parse_attachment_id(wrapper.value())
        assert local_cache.attachment.is_staged(VECTOR_ID, wrapper.value())
        staged = s.cache_dir / "staged" / wrapper.value()
        assert staged.read_bytes() == b"x"

    def test_rolling_back_discards_the_staged_file(self, setup, tmp_path):
        s = setup
        wrapper = self._wrapper(s)
        picked = tmp_path / "rolled.jpg"
        picked.write_bytes(b"z")
        wrapper.widget().fileWidget().setSelectedFileNames([str(picked)])
        attachment_id = wrapper.value()
        staged = s.cache_dir / "staged" / attachment_id
        assert staged.exists()

        s.layer.startEditing()
        s.layer.changeAttributeValue(
            s.feature.id(), s.layer.fields().indexOf("photo"), attachment_id
        )
        s.layer.rollBack()

        # Nothing references the file any more, so it would leak in the cache
        assert not staged.exists()

    def test_an_unsaved_feature_can_still_attach(self, setup, tmp_path):
        from qgis.core import QgsFeature, QgsGeometry, QgsPointXY

        from plugin_dir.kumoy import local_cache

        s = setup
        # kumoy_id is only assigned on commit, so a new feature has none
        unsaved = QgsFeature(s.layer.fields())
        unsaved.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(1, 1)))
        wrapper = self._wrapper(s, feature=unsaved)
        picked = tmp_path / "new.jpg"
        picked.write_bytes(b"y")

        wrapper.widget().fileWidget().setSelectedFileNames([str(picked)])

        assert local_cache.attachment.is_staged(VECTOR_ID, wrapper.value())
