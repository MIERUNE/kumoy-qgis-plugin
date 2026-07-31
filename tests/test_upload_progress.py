"""Issue #538: 複数レイヤーのアップロードを1つの進捗ダイアログで扱う挙動のテスト。"""

from types import SimpleNamespace

import pytest

from plugin_dir.ui.layers import convert_local
from plugin_dir.ui.layers.upload_progress import UploadProgressDialog, upload_progress


@pytest.fixture
def memory_layers(qgis_app):
    """メモリレイヤーを作り、QgsApplication の破棄前に片付ける。"""
    from qgis.core import QgsVectorLayer
    from qgis.PyQt import sip

    created = []

    def make(names):
        layers = [
            QgsVectorLayer("Point?crs=EPSG:4326", name, "memory") for name in names
        ]
        assert all(layer.isValid() for layer in layers)
        created.extend(layers)
        return layers

    yield make

    for layer in created:
        if not sip.isdeleted(layer):
            sip.delete(layer)


def test_overall_progress_spans_all_layers(qgis_app):
    dialog = UploadProgressDialog(4)

    assert dialog._overall_bar.maximum() == 400
    assert dialog._overall_bar.value() == 0

    dialog.begin_layer("roads", 2)
    assert dialog._overall_bar.value() == 200

    dialog.set_layer_progress(50)
    assert dialog._layer_bar.value() == 50
    # 3レイヤー目の途中 = 全体の 250/400
    assert dialog._overall_bar.value() == 250

    # レイヤー側の値は 0-100 に丸める
    dialog.set_layer_progress(180)
    assert dialog._layer_bar.value() == 100
    assert dialog._overall_bar.value() == 300

    dialog.deleteLater()


def test_single_layer_hides_overall_progress(qgis_app):
    dialog = UploadProgressDialog(1)

    assert dialog._overall_bar.isHidden()
    assert dialog._overall_label.isHidden()

    dialog.deleteLater()


def test_cancel_is_reported_once_and_does_not_close(qgis_app):
    dialog = UploadProgressDialog(3)
    emitted = []
    dialog.canceled.connect(lambda: emitted.append(True))

    # Esc・×ボタン相当。キャンセル要求として扱い、ダイアログは閉じない。
    dialog.reject()

    assert dialog.is_canceled()
    assert emitted == [True]
    assert dialog.result() == 0  # accept() されていない

    # 2回目のキャンセルは無視する（残りレイヤー分だけ押させない）
    dialog.request_cancel()
    assert emitted == [True]

    dialog.deleteLater()


def test_context_manager_closes_the_dialog_even_on_error(qgis_app):
    with upload_progress(2) as dialog:
        assert dialog.isVisible()
        opened = dialog

    assert not opened.isVisible()

    # 変換が例外で抜けてもモーダルダイアログを残さない
    with pytest.raises(RuntimeError):
        with upload_progress(2) as dialog:
            raise RuntimeError("boom")

    assert not dialog.isVisible()


def _stub_layer_limits(monkeypatch):
    project = SimpleNamespace(
        team=SimpleNamespace(organization=SimpleNamespace(id="org"))
    )
    organization = SimpleNamespace(
        subscriptionPlan="plan",
        storageUnits=0,
        usage=SimpleNamespace(vectors=0, rasters=0),
    )
    limits = SimpleNamespace(maxVectors=10, maxRasters=10)
    monkeypatch.setattr(
        convert_local.api.project, "get_project", lambda project_id: project
    )
    monkeypatch.setattr(
        convert_local.api.organization,
        "get_organization",
        lambda organization_id: organization,
    )
    monkeypatch.setattr(
        convert_local.api.plan,
        "get_plan_limits",
        lambda subscription_plan, storage_units: limits,
    )


def _accept_all_layers(monkeypatch):
    monkeypatch.setattr(
        convert_local,
        "LayerSelectDialog",
        lambda layers, **kwargs: SimpleNamespace(selected_layers=layers),
    )
    monkeypatch.setattr(
        convert_local, "exec_dialog", lambda dialog: convert_local.QDIALOG_CODE.Accepted
    )
    monkeypatch.setattr(
        convert_local,
        "iface",
        SimpleNamespace(
            mainWindow=lambda: None,
            mapCanvas=lambda: SimpleNamespace(refresh=lambda: None),
        ),
    )


def test_cancelling_mid_batch_skips_remaining_layers(
    qgis_app, memory_layers, monkeypatch
):
    layers = memory_layers(["a", "b", "c", "d"])
    monkeypatch.setattr(convert_local, "get_local_layers", lambda: layers)
    _stub_layer_limits(monkeypatch)
    _accept_all_layers(monkeypatch)

    uploaded = []

    def convert(layer, project_id, progress):
        uploaded.append(layer.name())
        if layer.name() == "b":
            # 2つ目のアップロード中にユーザーがキャンセルを押した状況
            progress.request_cancel()
            return (False, None)
        return (True, None)

    monkeypatch.setattr(convert_local, "convert_to_kumoy", convert)

    result = convert_local.convert_local_layers("project")

    # キャンセルはMap保存自体の中止ではない: 変換済みのレイヤーは反映して保存を続ける
    assert not result.cancelled
    assert result.converted
    assert result.errors == []
    # 3つ目以降は一度もアップロードを試みない
    assert uploaded == ["a", "b"]
    assert result.skipped == ["b", "c", "d"]


def test_failures_are_collected_without_stopping_the_batch(
    qgis_app, memory_layers, monkeypatch
):
    layers = memory_layers(["a", "b", "c"])
    monkeypatch.setattr(convert_local, "get_local_layers", lambda: layers)
    _stub_layer_limits(monkeypatch)
    _accept_all_layers(monkeypatch)

    def convert(layer, project_id, progress):
        if layer.name() == "b":
            return (False, "boom")
        return (True, None)

    monkeypatch.setattr(convert_local, "convert_to_kumoy", convert)

    result = convert_local.convert_local_layers("project")

    assert not result.cancelled
    assert result.converted
    assert result.errors == [("b", "boom")]
    assert result.skipped == []
