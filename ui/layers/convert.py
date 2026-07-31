"""Entry points for converting local layers into Kumoy layers.

Vector and raster differ only in the upload step, so only that is delegated to
``_upload_vector`` / ``_upload_raster``; guards, style copy, layer-tree
replacement and error handling are written once here.
"""

from dataclasses import dataclass, field
from typing import Optional

from qgis.core import (
    Qgis,
    QgsMapLayer,
    QgsMessageLog,
    QgsProject,
    QgsRasterLayer,
    QgsReadWriteContext,
    QgsVectorLayer,
)
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.PyQt.QtXml import QDomDocument
from qgis.utils import iface

from ... import i18n
from ...kumoy import api, constants
from ...kumoy.api.error import format_api_error
from ..dialog_layer_select import LayerQuota, LayerSelectDialog
from ..error_handler import handle_api_error, refresh_kumoy_browser
from ..utils import get_local_layers
from ...pyqt_version import QDIALOG_CODE, exec_dialog
from . import _upload_raster, _upload_vector
from .upload_progress import UploadProgressDialog, upload_progress


@dataclass
class ConversionResult:
    cancelled: bool = False
    """Cancelled at the selection dialog, so the map save should be aborted too."""

    errors: list[tuple[str, str]] = field(default_factory=list)
    """Failures as (layer name, error)."""

    converted: bool = False
    """At least one layer was converted."""

    skipped: list[str] = field(default_factory=list)
    """Layers left local because the upload was cancelled.

    Unlike ``cancelled``, the save goes on: layers converted before the cancel
    are already in the project, and the rest are saved as they are.
    """


def convert_local_layers(project_id: str) -> ConversionResult:
    """Prompt the user to select and convert local layers (vector and raster).

    A single dialog lists both layer types in layer panel order. Each type
    has a plan-based count quota capping how many can be selected.

    Does not refresh the browser panel: callers run this while holding a browser
    item, which rebuilding the tree would destroy. Refresh at the end of the
    calling flow instead when ``converted`` is True.
    """
    local_layers = get_local_layers()
    if not local_layers:
        return ConversionResult()

    try:
        project = api.project.get_project(project_id)
        org_detail = api.organization.get_organization(project.team.organization.id)
        plan_limits = api.plan.get_plan_limits(
            org_detail.subscriptionPlan, org_detail.storageUnits
        )
    except Exception as e:
        handle_api_error(
            e, parent=None, log_prefix=i18n.tr("Failed to check layer limits")
        )
        return ConversionResult(cancelled=True)

    dialog = LayerSelectDialog(
        local_layers,
        vector_quota=LayerQuota(
            max_layers=plan_limits.maxVectors,
            current=org_detail.usage.vectors,
        ),
        raster_quota=LayerQuota(
            max_layers=plan_limits.maxRasters,
            current=org_detail.usage.rasters,
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
                # error is None means the user cancelled this upload: skip, not a failure
                result.skipped.append(layer.name())

    iface.mapCanvas().refresh()

    return result


def on_convert_layer_clicked(layer: QgsMapLayer, project_id: str) -> None:
    """Convert a single layer, from the layer panel context menu."""
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

    layer_name = layer.name()
    with upload_progress(1) as progress:
        progress.begin_layer(layer_name, 0)
        success, error = convert_layer_to_kumoy(layer, project_id, progress)

    if success:
        # Safe to refresh only on this path: no caller is holding a browser item
        refresh_kumoy_browser()
        iface.messageBar().pushMessage(
            constants.PLUGIN_NAME,
            i18n.tr("Layer '{}' converted to Kumoy successfully.").format(layer_name),
            level=Qgis.Success,
            duration=5,
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


def convert_layer_to_kumoy(
    layer: QgsMapLayer,
    project_id: str,
    progress: UploadProgressDialog,
) -> tuple[bool, Optional[str]]:
    """Upload one local layer and replace it with the resulting Kumoy layer.

    Args:
        progress: dialog from ``upload_progress()``; the caller must have called
            ``begin_layer()`` for this layer already.

    Returns:
        tuple: (success, error_message). (False, None) on user cancel, which the
        caller reports as a skip rather than an error.
    """
    if not layer or not layer.isValid():
        return (False, i18n.tr("The layer is no longer valid or has been removed."))

    try:
        project_index = _resolve_project_index(project_id)
        if project_index is None:
            raise Exception(i18n.tr("Project not found in organization list"))

        # trim name if too long
        name = layer.name()[: constants.MAX_CHARACTERS_VECTOR_NAME]

        if isinstance(layer, QgsVectorLayer):
            kumoy_layer = _upload_vector.upload(layer, project_index, name, progress)
        else:
            kumoy_layer = _upload_raster.upload(layer, project_index, name, progress)

        if kumoy_layer is None:
            return (False, None)  # user cancel

        _copy_layer_style(layer, kumoy_layer)
        _replace_layer_in_tree(layer, kumoy_layer)
        return (True, None)

    except Exception as e:
        error_msg = format_api_error(e)
        QgsMessageLog.logMessage(
            f"Error converting layer '{layer.name()}': {error_msg}",
            constants.LOG_CATEGORY,
            Qgis.Critical,
        )
        return (False, error_msg)


def _resolve_project_index(project_id: str) -> Optional[int]:
    """Find the PROJECT enum index for the upload algorithms.

    Must walk organizations and projects in the same order and with the same
    filter as UploadVectorAlgorithm/UploadRasterAlgorithm.initAlgorithm, or the
    index points at the wrong project.
    """
    idx = 0
    for org in api.organization.get_organizations():
        # Organizations pending deletion get a 404 from the project API
        if org.scheduledDeletionAt:
            continue
        for proj in api.project.get_projects_by_organization(org.id):
            if proj.id == project_id:
                return idx
            idx += 1
    return None


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
    root = QgsProject.instance().layerTreeRoot()
    original_layer_node = root.findLayer(local_layer.id())

    if original_layer_node:
        was_checked = original_layer_node.itemVisibilityChecked()
        parent_node = original_layer_node.parent()
        index = parent_node.children().index(original_layer_node)

        QgsProject.instance().addMapLayer(kumoy_layer, False)
        new_layer_node = parent_node.insertLayer(index, kumoy_layer)
        new_layer_node.setItemVisibilityChecked(was_checked)
        parent_node.removeChildNode(original_layer_node)
        QgsProject.instance().removeMapLayer(local_layer.id())
    else:
        # Fallback: add to root if original node not found
        QgsProject.instance().addMapLayer(kumoy_layer)
        QgsProject.instance().removeMapLayer(local_layer.id())

    iface.layerTreeView().setCurrentLayer(kumoy_layer)
