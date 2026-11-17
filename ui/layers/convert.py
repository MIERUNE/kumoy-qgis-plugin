"""Entry points for converting local layers into Kumoy layers.

Vector and raster differ only in the upload step, delegated to
``_upload_vector`` / ``_upload_raster``: both start a background task and
report back through callbacks on the main thread. Guards, style copy,
layer-tree replacement and error handling are written once here.

The single-layer conversion from the layer panel is fully asynchronous. The
batch conversion runs inside the map save (QgsProjectStorage.writeProject),
which needs the result synchronously, so it waits for each task in a local
event loop behind a modal progress dialog: QGIS keeps painting and Cancel
works, but nothing is pumped from inside the uploads.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Tuple, TypeVar

from qgis.core import (
    Qgis,
    QgsMapLayer,
    QgsMessageLog,
    QgsProject,
    QgsRasterLayer,
    QgsReadWriteContext,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QEventLoop
from qgis.PyQt.QtGui import QCursor
from qgis.PyQt.QtWidgets import QApplication, QMessageBox
from qgis.PyQt.QtXml import QDomDocument
from qgis.utils import iface

from ... import i18n
from ...kumoy import api, constants
from ...kumoy.api.error import format_api_error
from ...kumoy.api.models import OrganizationDetail
from ...kumoy.tasks import FunctionTask, run_task
from ...pyqt_version import QDIALOG_CODE, QT_CURSOR_SHAPE, exec_dialog, exec_event_loop
from ..dialog_layer_select import LayerQuota, LayerSelectDialog
from ..error_handler import handle_api_error, push_success, refresh_kumoy_browser
from ..utils import get_local_layers
from . import _upload_raster, _upload_vector
from .upload_progress import UploadProgressDialog, upload_progress

T = TypeVar("T")


@dataclass
class ConversionResult:
    cancelled: bool = False
    """Cancelled at the selection dialog, so the map save should be aborted too."""

    errors: List[Tuple[str, str]] = field(default_factory=list)
    """Failures as (layer name, error)."""

    converted: bool = False
    """At least one layer was converted."""

    skipped: List[str] = field(default_factory=list)
    """Layers left local because the upload was cancelled.

    Unlike ``cancelled``, the save goes on: layers converted before the cancel
    are already in the project, and the rest are saved as they are.
    """


# One conversion at a time: the batch's local event loop keeps QGIS
# responsive, so another conversion (or a save that converts) could start
_busy = False


def convert_local_layers(project_id: str) -> ConversionResult:
    """Ask which local layers to convert, upload them and swap them in.

    Synchronous (for the map save): returns when every upload has finished or
    was cancelled, while the UI keeps painting. Returns ``cancelled=True``
    when the user cancels the selection, the layer limits cannot be read, or
    a conversion is already running.

    Does not refresh the browser panel: callers run this while holding a browser
    item, which rebuilding the tree would destroy. Refresh at the end of the
    calling flow instead when ``converted`` is True.
    """
    global _busy
    local_layers = get_local_layers()
    if not local_layers:
        return ConversionResult()
    if _busy:
        return ConversionResult(cancelled=True)
    _busy = True
    try:
        return _convert_local_layers(project_id, local_layers)
    finally:
        _busy = False


def _convert_local_layers(
    project_id: str, local_layers: List[QgsMapLayer]
) -> ConversionResult:
    try:
        organization = _wait_with_busy_cursor(
            i18n.tr("Checking Kumoy layer limits"),
            lambda _task: _organization_of(project_id),
        )
    except Exception as e:
        handle_api_error(e, title=i18n.tr("Failed to check layer limits"))
        return ConversionResult(cancelled=True)

    dialog = LayerSelectDialog(
        local_layers,
        vector_quota=LayerQuota(
            max_layers=organization.planSettings.maxVectors,
            current=organization.usage.vectors,
        ),
        raster_quota=LayerQuota(
            max_layers=organization.planSettings.maxRasters,
            current=organization.usage.rasters,
        ),
    )
    if exec_dialog(dialog) != QDIALOG_CODE.Accepted:
        return ConversionResult(cancelled=True)

    selected_layers = dialog.selected_layers
    if not selected_layers:
        return ConversionResult()

    result = ConversionResult()
    with upload_progress(len(selected_layers)) as progress:
        for index, layer in enumerate(selected_layers):
            if progress.is_canceled():
                result.skipped.extend(
                    remaining.name() for remaining in selected_layers[index:]
                )
                break

            progress.begin_layer(layer.name(), index)
            success, error = convert_layer_to_kumoy(layer, project_id, progress)

            if success:
                result.converted = True
            elif error is not None:
                result.errors.append((layer.name(), error))
            else:
                # error is None means the user cancelled this upload
                result.skipped.append(layer.name())

    iface.mapCanvas().refresh()
    return result


def on_convert_layer_clicked(layer: QgsMapLayer, project_id: str) -> None:
    """Convert a single layer, from the layer panel context menu.

    Returns at once; the upload runs in the background with a progress dialog.
    """
    global _busy
    if not layer or not layer.isValid():
        QMessageBox.warning(
            None,
            i18n.tr("Invalid Layer"),
            i18n.tr("The selected layer is no longer valid or has been removed."),
        )
        return

    if not project_id:
        QMessageBox.warning(
            None,
            i18n.tr("No Project Selected"),
            i18n.tr("Please select a Kumoy project before converting a layer."),
        )
        return

    if _busy:
        return  # the running conversion's dialog is already on screen

    layer_name = layer.name()
    layer_id = layer.id()
    progress = UploadProgressDialog(1, iface.mainWindow())
    progress.show()
    progress.begin_layer(layer_name, 0)

    def finished(kumoy_layer: Optional[QgsMapLayer], error: Optional[str]) -> None:
        global _busy
        _busy = False
        progress.finish()
        if kumoy_layer is not None:
            # The project may have changed while uploading
            local = QgsProject.instance().mapLayer(layer_id)
            if local is None:
                QgsProject.instance().addMapLayer(kumoy_layer)
            else:
                _swap_in(local, kumoy_layer)
            # Safe to refresh only on this path: no caller is holding a browser item
            refresh_kumoy_browser()
            push_success(
                i18n.tr("Layer '{}' converted to Kumoy successfully.").format(
                    layer_name
                )
            )
        elif error is not None:
            # error is None means the user cancelled, so stay quiet
            QMessageBox.warning(
                None,
                i18n.tr("Conversion Failed"),
                i18n.tr("Failed to convert layer '{}' to Kumoy:\n{}").format(
                    layer_name, error
                ),
            )

    _busy = True
    try:
        _start_upload(layer, project_id, progress, finished)
    except Exception as e:
        finished(None, _log_failure(layer_name, e))


def convert_layer_to_kumoy(
    layer: QgsMapLayer,
    project_id: str,
    progress: UploadProgressDialog,
) -> Tuple[bool, Optional[str]]:
    """Upload one local layer and replace it with the resulting Kumoy layer.

    Blocks in a local event loop until the upload ends (see module docstring).

    Args:
        progress: dialog from ``upload_progress()``; the caller must have called
            ``begin_layer()`` for this layer already.

    Returns:
        tuple: (success, error_message). (False, None) on user cancel, which the
        caller reports as a skip rather than an error.
    """
    if not layer or not layer.isValid():
        return (False, i18n.tr("The layer is no longer valid or has been removed."))

    outcome: List[Tuple[Optional[QgsMapLayer], Optional[str]]] = []
    loop = QEventLoop()

    def finished(kumoy_layer: Optional[QgsMapLayer], error: Optional[str]) -> None:
        outcome.append((kumoy_layer, error))
        loop.quit()

    try:
        _start_upload(layer, project_id, progress, finished)
    except Exception as e:
        return (False, _log_failure(layer.name(), e))
    if not outcome:
        exec_event_loop(loop)

    kumoy_layer, error = outcome[0]
    if kumoy_layer is None:
        return (False, error)
    try:
        _swap_in(layer, kumoy_layer)
    except Exception as e:
        return (False, _log_failure(layer.name(), e))
    return (True, None)


def _start_upload(
    layer: QgsMapLayer,
    project_id: str,
    progress: UploadProgressDialog,
    finished: Callable[[Optional[QgsMapLayer], Optional[str]], None],
) -> None:
    """Start the upload; `finished(kumoy_layer, error)` is called exactly once.

    (None, None) means canceled.
    """
    name = layer.name()[: constants.MAX_CHARACTERS_VECTOR_NAME]
    uploader = _upload_vector if isinstance(layer, QgsVectorLayer) else _upload_raster
    task = None
    ended = False

    def cancel() -> None:
        if task is not None and not ended:
            task.cancel()

    def end(kumoy_layer: Optional[QgsMapLayer], error: Optional[str]) -> None:
        nonlocal ended
        # The task is deleted after it reports back: no more cancel requests
        ended = True
        progress.canceled.disconnect(cancel)
        finished(kumoy_layer, error)

    progress.canceled.connect(cancel)
    try:
        task = uploader.upload(
            layer,
            project_id,
            name,
            on_progress=progress.set_layer_progress,
            on_done=lambda kumoy_layer: end(kumoy_layer, None),
            on_error=lambda e: end(None, _log_failure(layer.name(), e)),
        )
    except Exception:
        progress.canceled.disconnect(cancel)
        raise
    if progress.is_canceled():
        # Cancel pressed while a previous layer was running must not be lost
        cancel()


def _swap_in(local_layer: QgsMapLayer, kumoy_layer: QgsMapLayer) -> None:
    _copy_layer_style(local_layer, kumoy_layer)
    _replace_layer_in_tree(local_layer, kumoy_layer)


def _log_failure(layer_name: str, error: Exception) -> str:
    message = format_api_error(error)
    QgsMessageLog.logMessage(
        f"Error converting layer '{layer_name}': {message}",
        constants.LOG_CATEGORY,
        Qgis.Critical,
    )
    return message


def _organization_of(project_id: str) -> OrganizationDetail:
    project = api.project.get_project(project_id)
    return api.organization.get_organization(project.team.organizationId)


def run_and_wait(description: str, fn: Callable[[FunctionTask], T]) -> T:
    """Run ``fn(task)`` in a QgsTask and wait for it, keeping the UI alive.

    Returns fn's result or raises its exception.
    """
    loop = QEventLoop()
    task = run_task(description, fn)
    # Both are emitted on this thread after the task ends, so connecting
    # before exec cannot miss them
    task.taskCompleted.connect(loop.quit)
    task.taskTerminated.connect(loop.quit)
    exec_event_loop(loop)
    if task.exception is not None:
        raise task.exception
    return task.result


def _wait_with_busy_cursor(description: str, fn: Callable[[Any], T]) -> T:
    # No dialog is open yet; show that something is happening
    QApplication.setOverrideCursor(QCursor(QT_CURSOR_SHAPE.WaitCursor))
    try:
        return run_and_wait(description, fn)
    finally:
        QApplication.restoreOverrideCursor()


def _copy_layer_style(source_layer: QgsMapLayer, target_layer: QgsMapLayer) -> None:
    """Copy style from source layer to target layer"""
    doc = QDomDocument()
    elem = doc.createElement("qgis")
    doc.appendChild(elem)
    context = QgsReadWriteContext()

    source_layer.writeStyle(elem, doc, "", context, QgsMapLayer.AllStyleCategories)
    target_layer.readStyle(elem, "", context, QgsMapLayer.AllStyleCategories)
    if isinstance(target_layer, QgsRasterLayer):
        _upload_raster.repair_nan_classification(source_layer, target_layer)
    target_layer.triggerRepaint()


def _replace_layer_in_tree(local_layer: QgsMapLayer, kumoy_layer: QgsMapLayer) -> None:
    """Swap in the Kumoy layer at the original legend position and visibility."""
    project = QgsProject.instance()
    original_layer_node = project.layerTreeRoot().findLayer(local_layer.id())

    if original_layer_node:
        was_checked = original_layer_node.itemVisibilityChecked()
        parent_node = original_layer_node.parent()
        index = parent_node.children().index(original_layer_node)

        project.addMapLayer(kumoy_layer, False)
        new_layer_node = parent_node.insertLayer(index, kumoy_layer)
        new_layer_node.setItemVisibilityChecked(was_checked)
        parent_node.removeChildNode(original_layer_node)
    else:
        # Not in the legend: add the new layer at the top
        project.addMapLayer(kumoy_layer)
    project.removeMapLayer(local_layer.id())

    iface.layerTreeView().setCurrentLayer(kumoy_layer)
