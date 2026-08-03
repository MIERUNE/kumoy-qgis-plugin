"""添付機能の結線テスト。

configure.py が組み立てるウィジェット設定と external_storage.py の実装が、実際の
QGIS の ExternalResource ウィジェットで噛み合うかを検証する。ここが崩れると
「フォームに画像が出ない」「ファイルを選んでもアップロードされない」という形で
静かに壊れるため、ウィジェット越しに一往復させて確認する。

ネットワークとファイル I/O はスタブ化し、QGIS 側との契約だけを見る。
"""

import types

import pytest

VECTOR_ID = "11111111-1111-4111-8111-111111111111"
COLUMN_ID = "22222222-2222-4222-8222-222222222222"
NAME_COLUMN_ID = "99999999-9999-4999-8999-999999999999"
VALUE = "aaaaaaaa-3333-4333-8333-333333333333.jpg"


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

        uploaded = {}

        def fake_upload(
            vector_id,
            kumoy_id,
            vector_column_id,
            file_path,
            progress_callback=None,
            is_canceled=None,
        ):
            uploaded.update(
                vector_id=vector_id,
                kumoy_id=kumoy_id,
                vector_column_id=vector_column_id,
                file_path=file_path,
            )
            return VALUE

        monkeypatch.setattr(attachment_domain, "upload", fake_upload)

        cached_image = tmp_path / "cached.jpg"
        cached_image.write_bytes(b"IMG")
        fetched = {}
        monkeypatch.setattr(
            local_cache.attachment,
            "is_cached",
            lambda vector_id, value: (
                fetched.update(vector_id=vector_id, value=value) or True
            ),
        )
        monkeypatch.setattr(
            local_cache.attachment,
            "get_cache_path",
            lambda vector_id, value: str(cached_image),
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
            feature=feature,
            uploaded=uploaded,
            fetched=fetched,
            registry=QgsGui.editorWidgetRegistry(),
            external_storage=external_storage,
            app=QgsApplication,
        )

        external_storage.unregister()

    def _wrapper(self, s):
        from qgis.PyQt.QtWidgets import QWidget

        idx = s.layer.fields().indexOf("photo")
        setup = s.layer.editorWidgetSetup(idx)
        # parent は wrapper より長生きさせる（GC されると wrapper が無効化される）
        s.parent = QWidget()
        wrapper = s.registry.create(
            "ExternalResource", s.layer, idx, setup.config(), None, s.parent
        )
        wrapper.setFeature(s.feature)
        return wrapper

    def test_only_attachment_columns_get_the_widget(self, setup):
        s = setup
        photo_idx = s.layer.fields().indexOf("photo")
        name_idx = s.layer.fields().indexOf("name")

        assert s.layer.editorWidgetSetup(photo_idx).type() == "ExternalResource"
        # string カラムは既定のまま（添付扱いにしてしまわない）
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

        wrapper.setValues(VALUE, [])

        # 属性値だけでは vector_id が分からないので、DefaultRoot 経由で渡ってくる
        # ことがこの機能の前提。ここが壊れると画像が出なくなる
        assert s.fetched == {"vector_id": VECTOR_ID, "value": VALUE}

    def test_selecting_a_file_uploads_and_writes_the_value(self, setup, tmp_path):
        s = setup
        wrapper = self._wrapper(s)
        picked = tmp_path / "picked.jpg"
        picked.write_bytes(b"x")

        wrapper.widget().fileWidget().setSelectedFileNames([str(picked)])

        # StorageUrl 式が地物ごとに評価され、kumoy_id が埋まっていること
        assert s.uploaded == {
            "vector_id": VECTOR_ID,
            "kumoy_id": 42,
            "vector_column_id": COLUMN_ID,
            "file_path": str(picked),
        }
        # ウィジェットは doStore の url() をそのまま属性値にする。この値が
        # サーバ側の遷移ルール（NULL → 発行済みの値のみ許可）を通る形でなければならない
        assert wrapper.value() == VALUE
