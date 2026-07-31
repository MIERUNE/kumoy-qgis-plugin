from typing import Optional

from qgis.core import (
    Qgis,
    QgsMapLayer,
    QgsMessageLog,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProject,
    QgsReadWriteContext,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.PyQt.QtXml import QDomDocument
from qgis.utils import iface

import processing

from ... import i18n
from ...kumoy import api, constants
from ...kumoy.api.error import format_api_error
from .upload_progress import UploadProgressDialog, upload_progress


def on_convert_to_kumoy_clicked(layer: QgsVectorLayer, project_id: str) -> None:
    # Validate layer before proceeding
    if not layer or not layer.isValid():
        QMessageBox.warning(
            None,
            i18n.tr("Invalid Layer"),
            i18n.tr("The selected layer is no longer valid or has been removed."),
        )
        return

    layer_name = layer.name()

    if not project_id:
        QMessageBox.warning(
            None,
            i18n.tr("No Project Selected"),
            i18n.tr("Please select a Kumoy project before converting a layer."),
        )
        return

    with upload_progress(1) as progress:
        progress.begin_layer(layer_name, 0)
        success, error = convert_to_kumoy(layer, project_id, progress)

    if success:
        iface.messageBar().pushMessage(
            constants.PLUGIN_NAME,
            i18n.tr("Layer '{}' converted to Kumoy successfully.").format(layer_name),
            level=Qgis.Success,
            duration=5,
        )
    elif error is not None:
        # error is None ならユーザーが自分でキャンセルしたのでエラー表示しない
        QMessageBox.warning(
            None,
            i18n.tr("Conversion Failed"),
            i18n.tr("Failed to convert layer '{}' to Kumoy:\n{}").format(
                layer_name, error
            ),
        )


def convert_to_kumoy(
    layer: QgsVectorLayer,
    project_id: str,
    progress: UploadProgressDialog,
) -> tuple[bool, Optional[str]]:
    """Convert a vector layer to Kumoy

    Args:
        progress: 呼び出し側が ``upload_progress()`` で用意した進捗ダイアログ。
            ここでは報告とキャンセル監視だけを行い、開閉はしない。
            対象レイヤーの ``begin_layer()`` は呼び出し側が済ませておくこと。

    Returns:
        tuple: (success: bool, error_message: str or None)。ユーザーが中断した場合は
        (False, None)（呼び出し側はエラー表示しない）。
    """

    # Validate layer before proceeding
    if not layer or not layer.isValid():
        return (False, i18n.tr("The layer is no longer valid or has been removed."))

    vector_name = layer.name()
    # trim name if too long
    if len(vector_name) > constants.MAX_CHARACTERS_VECTOR_NAME:
        vector_name = vector_name[: constants.MAX_CHARACTERS_VECTOR_NAME]

    feedback = QgsProcessingFeedback()

    # processing.run はメインスレッドを塞ぐので、進捗更新のたびにイベントを
    # 回してダイアログの再描画とキャンセルボタンの押下を通す。
    def update_progress(value: float) -> None:
        progress.set_layer_progress(value)
        QCoreApplication.processEvents()

    feedback.progressChanged.connect(update_progress)
    progress.canceled.connect(feedback.cancel)
    if progress.is_canceled():
        # 前のレイヤーの処理中に押されたキャンセルを取りこぼさない
        feedback.cancel()

    try:
        context = QgsProcessingContext()

        # Get the project index for the processing algorithm using project id
        organizations = api.organization.get_organizations()
        all_projects = []
        for org in organizations:
            # Must match the filtering in UploadVectorAlgorithm.initAlgorithm:
            # both sides index into the same flattened project list
            if org.scheduledDeletionAt:
                continue
            org_projects = api.project.get_projects_by_organization(org.id)
            all_projects.extend(org_projects)

        # Find the index of current project
        project_index = None
        for idx, proj in enumerate(all_projects):
            if proj.id == project_id:
                project_index = idx
                break

        if project_index is None:
            raise Exception(i18n.tr("Project not found in organization list"))

        # Run the upload algorithm
        result = processing.run(
            "kumoy:uploadvector",
            {
                "INPUT": layer,
                "PROJECT": project_index,
                "VECTOR_NAME": vector_name,
                "SELECTED_FIELDS": [],
            },
            context=context,
            feedback=feedback,
        )

        # Check if cancelled
        if feedback.isCanceled():
            iface.messageBar().pushMessage(
                constants.PLUGIN_NAME,
                i18n.tr("Upload cancelled"),
                level=Qgis.Warning,
                duration=3,
            )
            return (False, None)

        if not result or "VECTOR_ID" not in result:
            raise Exception(i18n.tr("Upload failed - unable to get vector id"))

        vector_id = result["VECTOR_ID"]

        # Get updated vector details
        vector = api.vector.get_vector(vector_id)

        # Create Kumoy layer URI
        vector_uri = f"project_id={vector.projectId};vector_id={vector.id};vector_name={vector.name};vector_type={vector.type};"

        # Create the layer
        kumoy_layer = QgsVectorLayer(
            vector_uri, vector.name, constants.DATA_PROVIDER_KEY
        )

        if kumoy_layer.isValid():
            # Configure kumoy_id as read-only
            field_idx = kumoy_layer.fields().indexOf("kumoy_id")
            if field_idx >= 0:
                config = kumoy_layer.editFormConfig()
                config.setReadOnly(field_idx, True)
                kumoy_layer.setEditFormConfig(config)

            # Copy layer style from original layer
            _copy_layer_style(layer, kumoy_layer)

            # Get original layer position in legend
            root = QgsProject.instance().layerTreeRoot()
            original_layer_node = root.findLayer(layer.id())

            if original_layer_node:
                # Replace local layer by new Kumoy layer at the same index position
                was_checked = original_layer_node.itemVisibilityChecked()
                parent_node = original_layer_node.parent()
                index = parent_node.children().index(original_layer_node)

                QgsProject.instance().addMapLayer(kumoy_layer, False)
                new_layer_node = parent_node.insertLayer(index, kumoy_layer)
                new_layer_node.setItemVisibilityChecked(was_checked)
                parent_node.removeChildNode(original_layer_node)
                QgsProject.instance().removeMapLayer(layer.id())

                # Set the new layer as the current/selected layer
                layer_tree_view = iface.layerTreeView()
                new_layer_node = root.findLayer(kumoy_layer.id())
                if new_layer_node:
                    layer_tree_view.setCurrentLayer(kumoy_layer)
            else:
                # Fallback: add to root if original node not found
                QgsProject.instance().addMapLayer(kumoy_layer)
                QgsProject.instance().removeMapLayer(layer.id())

                # Set as current layer
                iface.layerTreeView().setCurrentLayer(kumoy_layer)

        else:
            error_msg = (
                kumoy_layer.error().message()
                if kumoy_layer.error()
                else "Unknown error"
            )
            raise Exception(
                i18n.tr("Failed to create Kumoy layer: {}").format(error_msg)
            )

        # Success
        return (True, None)

    except Exception as e:
        error_msg = format_api_error(e)
        QgsMessageLog.logMessage(
            f"Error converting layer: {error_msg}",
            constants.LOG_CATEGORY,
            Qgis.Critical,
        )
        return (False, error_msg)

    finally:
        # ダイアログは次のレイヤーでも使うので、この feedback との接続だけ切る
        progress.canceled.disconnect(feedback.cancel)


def _copy_layer_style(
    source_layer: QgsVectorLayer, target_layer: QgsVectorLayer
) -> None:
    """Copy style from source layer to target layer"""
    doc = QDomDocument()
    elem = doc.createElement("qgis")
    doc.appendChild(elem)
    context = QgsReadWriteContext()

    source_layer.writeStyle(elem, doc, "", context, QgsMapLayer.AllStyleCategories)
    target_layer.readStyle(elem, "", context, QgsMapLayer.AllStyleCategories)
    target_layer.triggerRepaint()
