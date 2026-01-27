import processing
from typing import Optional

from qgis.core import (
    Qgis,
    QgsMessageLog,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import (
    QMessageBox,
    QProgressDialog,
)
from qgis.utils import iface

from ...kumoy import api, constants
from ...kumoy.api.error import format_api_error
from ...pyqt_version import (
    QT_APPLICATION_MODAL,
)
from ...settings_manager import get_settings


def tr(message: str, context: str = "@default") -> str:
    return QCoreApplication.translate(context, message)


def on_convert_to_kumoy_clicked(layer: QgsVectorLayer) -> None:
    # Validate layer before proceeding
    if not layer or not layer.isValid():
        QMessageBox.warning(
            None,
            tr("Invalid Layer"),
            tr("The selected layer is no longer valid or has been removed."),
        )
        return

    layer_name = layer.name()
    project_id = get_settings().selected_project_id

    if not project_id:
        QMessageBox.warning(
            None,
            tr("No Project Selected"),
            tr("Please select a Kumoy project before converting a layer."),
        )
        return

    success, error = convert_to_kumoy(layer, project_id)

    if success:
        iface.messageBar().pushMessage(
            constants.PLUGIN_NAME,
            tr("Layer '{}' converted to Kumoy successfully.").format(layer_name),
            level=Qgis.Success,
            duration=5,
        )
    else:
        QMessageBox.warning(
            None,
            tr("Conversion Failed"),
            tr("Failed to convert layer '{}' to Kumoy:\n{}").format(layer_name, error),
        )


def convert_to_kumoy(
    layer: QgsVectorLayer, project_id: str
) -> tuple[bool, Optional[str]]:
    """Convert a vector layer to Kumoy
    Returns:
        tuple: (success: bool, error_message: str or None)
    """

    # Validate layer before proceeding
    if not layer or not layer.isValid():
        return (False, tr("The layer is no longer valid or has been removed."))

    progress_dialog = None

    try:
        vector_name = layer.name()
        # trim name if too long
        if len(vector_name) > constants.MAX_CHARACTERS_VECTOR_NAME:
            vector_name = vector_name[: constants.MAX_CHARACTERS_VECTOR_NAME]

        # Create progress dialog
        progress_dialog = QProgressDialog(
            tr("Uploading layer '{}'...").format(vector_name),
            tr("Cancel"),
            0,
            100,
            iface.mainWindow(),
        )
        progress_dialog.setWindowTitle(tr("Kumoy Upload"))
        progress_dialog.setWindowModality(QT_APPLICATION_MODAL)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setValue(10)
        progress_dialog.show()

        # Issue #356: ensure dialog is drawn properly on Windows
        progress_dialog.repaint()
        QCoreApplication.processEvents()
        progress_dialog.repaint()
        QCoreApplication.processEvents()

        # Create processing context and feedback
        context = QgsProcessingContext()
        feedback = QgsProcessingFeedback()

        # Connect feedback to progress dialog
        def update_progress(progress):
            if progress_dialog:
                # Scale progress: 10-90% for upload
                progress_dialog.setValue(10 + int(progress * 0.8))

        feedback.progressChanged.connect(update_progress)

        # Handle cancel
        progress_dialog.canceled.connect(feedback.cancel)

        # Get the project index for the processing algorithm using project id
        organizations = api.organization.get_organizations()
        all_projects = []
        for org in organizations:
            org_projects = api.project.get_projects_by_organization(org.id)
            all_projects.extend(org_projects)

        # Find the index of current project
        project_index = None
        for idx, proj in enumerate(all_projects):
            if proj.id == project_id:
                project_index = idx
                break

        if project_index is None:
            raise Exception(tr("Project not found in organization list"))

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
            progress_dialog.close()
            iface.messageBar().pushMessage(
                constants.PLUGIN_NAME,
                tr("Upload cancelled"),
                level=Qgis.Warning,
                duration=3,
            )
            return (False, tr("Upload cancelled by user"))

        if not result or "VECTOR_ID" not in result:
            raise Exception(tr("Upload failed - unable to get vector id"))

        vector_id = result["VECTOR_ID"]

        progress_dialog.close()
        progress_dialog = None

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

            original_renderer = layer.renderer()
            if original_renderer:
                kumoy_layer.setRenderer(original_renderer.clone())

            # Get original layer position in legend
            root = QgsProject.instance().layerTreeRoot()
            original_layer_node = root.findLayer(layer.id())

            if original_layer_node:
                # Replace local layer by new Kumoy layer at the same index position
                parent_node = original_layer_node.parent()
                index = parent_node.children().index(original_layer_node)

                QgsProject.instance().addMapLayer(kumoy_layer, False)
                parent_node.insertLayer(index, kumoy_layer)
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
            raise Exception(tr("Failed to create Kumoy layer: {}").format(error_msg))

        # Success
        return (True, None)

    except Exception as e:
        if progress_dialog:
            progress_dialog.close()

        error_msg = format_api_error(e)
        QgsMessageLog.logMessage(
            f"Error converting layer: {error_msg}",
            constants.LOG_CATEGORY,
            Qgis.Critical,
        )
        return (False, error_msg)
