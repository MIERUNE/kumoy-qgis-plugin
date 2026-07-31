"""Issue #538: one progress dialog shared by a batch of layer uploads."""

from types import SimpleNamespace

import pytest
from qgis.PyQt.QtGui import QFontMetrics

from plugin_dir.ui.layers import convert
from plugin_dir.ui.layers.upload_progress import UploadProgressDialog, upload_progress


@pytest.fixture
def memory_layers(qgis_app):
    """Make memory layers and delete them before QgsApplication tears down."""
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
    assert dialog._overall_bar.value() == 250

    # Out-of-range layer progress is clamped
    dialog.set_layer_progress(180)
    assert dialog._layer_bar.value() == 100
    assert dialog._overall_bar.value() == 300

    dialog.deleteLater()


def test_single_layer_hides_overall_progress(qgis_app):
    dialog = UploadProgressDialog(1)

    assert dialog._overall_bar.isHidden()
    assert dialog._overall_label.isHidden()

    dialog.deleteLater()


def test_long_layer_name_is_elided_to_one_line(qgis_app):
    dialog = UploadProgressDialog(2)
    dialog.show()

    dialog.begin_layer("short", 0)
    one_line_height = dialog._layer_label.height()

    long_name = "very long layer name " * 20
    dialog.begin_layer(long_name, 1)

    label = dialog._layer_label
    assert not label.wordWrap()
    assert label.height() == one_line_height
    assert label.text() != long_name
    assert "…" in label.text()
    assert QFontMetrics(label.font()).horizontalAdvance(label.text()) <= label.width()
    assert long_name in label.toolTip()

    dialog.finish()


def test_cancel_is_reported_once_and_does_not_close(qgis_app):
    dialog = UploadProgressDialog(3)
    emitted = []
    dialog.canceled.connect(lambda: emitted.append(True))

    # Esc / window close button
    dialog.reject()

    assert dialog.is_canceled()
    assert emitted == [True]
    assert dialog.result() == 0  # not accept()ed

    dialog.request_cancel()
    assert emitted == [True]

    dialog.deleteLater()


def test_context_manager_closes_the_dialog_even_on_error(qgis_app):
    with upload_progress(2) as dialog:
        assert dialog.isVisible()
        opened = dialog

    assert not opened.isVisible()

    # An exception must not leave a modal dialog behind
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
    monkeypatch.setattr(convert.api.project, "get_project", lambda project_id: project)
    monkeypatch.setattr(
        convert.api.organization,
        "get_organization",
        lambda organization_id: organization,
    )
    monkeypatch.setattr(
        convert.api.plan,
        "get_plan_limits",
        lambda subscription_plan, storage_units: limits,
    )


def _accept_all_layers(monkeypatch):
    monkeypatch.setattr(
        convert,
        "LayerSelectDialog",
        lambda layers, **kwargs: SimpleNamespace(selected_layers=layers),
    )
    monkeypatch.setattr(
        convert, "exec_dialog", lambda dialog: convert.QDIALOG_CODE.Accepted
    )
    monkeypatch.setattr(
        convert,
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
    monkeypatch.setattr(convert, "get_local_layers", lambda: layers)
    _stub_layer_limits(monkeypatch)
    _accept_all_layers(monkeypatch)

    uploaded = []

    def fake_convert(layer, project_id, progress):
        uploaded.append(layer.name())
        if layer.name() == "b":
            # User presses cancel during the second upload
            progress.request_cancel()
            return (False, None)
        return (True, None)

    monkeypatch.setattr(convert, "convert_layer_to_kumoy", fake_convert)

    result = convert.convert_local_layers("project")

    # Cancel is not an abort of the save: already-converted layers still count
    assert not result.cancelled
    assert result.converted
    assert result.errors == []
    assert uploaded == ["a", "b"]
    assert result.skipped == ["b", "c", "d"]


def test_failures_are_collected_without_stopping_the_batch(
    qgis_app, memory_layers, monkeypatch
):
    layers = memory_layers(["a", "b", "c"])
    monkeypatch.setattr(convert, "get_local_layers", lambda: layers)
    _stub_layer_limits(monkeypatch)
    _accept_all_layers(monkeypatch)

    def fake_convert(layer, project_id, progress):
        if layer.name() == "b":
            return (False, "boom")
        return (True, None)

    monkeypatch.setattr(convert, "convert_layer_to_kumoy", fake_convert)

    result = convert.convert_local_layers("project")

    assert not result.cancelled
    assert result.converted
    assert result.errors == [("b", "boom")]
    assert result.skipped == []
