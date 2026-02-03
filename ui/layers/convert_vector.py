import processing
from typing import Optional

from qgis.core import (
    Qgis,
    QgsMessageLog,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProject,
    QgsReadWriteContext,
    QgsMapLayer,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import (
    QMessageBox,
    QProgressDialog,
)
from qgis.PyQt.QtXml import QDomDocument
from qgis.utils import iface

from ...kumoy import api, constants
from ...kumoy.api.error import format_api_error
from ...pyqt_version import (
    QT_APPLICATION_MODAL,
)


def tr(message: str, context: str = "@default") -> str:
    return QCoreApplication.translate(context, message)


def on_convert_to_kumoy_clicked(layer: QgsVectorLayer, project_id: str) -> None:
    # Validate layer before proceeding
    if not layer or not layer.isValid():
        QMessageBox.warning(
            None,
            tr("Invalid Layer"),
            tr("The selected layer is no longer valid or has been removed."),
        )
        return

    layer_name = layer.name()

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


def get_local_vector_layers() -> list[QgsVectorLayer]:
    """Get all local vector layers in current QGIS project"""
    local_layers = []
    for layer in QgsProject.instance().mapLayers().values():
        # skip if it is not a valid vector layer
        if not layer or not layer.isValid() or not isinstance(layer, QgsVectorLayer):
            continue
        provider = layer.dataProvider()
        if not provider or provider.name() == constants.DATA_PROVIDER_KEY:
            continue

        local_layers.append(layer)

    return local_layers


def check_vector_layers_modified(layers: list[QgsVectorLayer]) -> bool:
    for layer in layers:
        if isinstance(layer, QgsVectorLayer) and layer.isModified():
            return True
    return False


def convert_multiple_layers_to_kumoy(
    layers: list[QgsVectorLayer], project_id: str
) -> list[tuple[str, str]]:
    """Convert multiple layers to Kumoy
    Returns: list of (layer_name, error_message) for failed conversions
    """
    conversion_errors = []
    for layer in layers:
        success, error = convert_to_kumoy(layer, project_id)
        if not success:
            conversion_errors.append((layer.name(), error))
    return conversion_errors


def prompt_and_convert_local_layers(
    project_id: str,
    tr_func,
    check_unsaved_edits: bool = True,
    error_title: str = None,
) -> tuple[bool, list[tuple[str, str]]]:
    """Prompt user to convert local layers and execute if confirmed.

    Args:
        project_id: Project ID to convert layers to
        tr_func: Translation function to use for messages
        check_unsaved_edits: If True, check for unsaved edits and block if found
        error_title: Title for error dialog (default: "Cannot Save Map")

    Returns:
        tuple: (user_confirmed: bool, conversion_errors: list)
               user_confirmed is False if user declined or if unsaved edits blocked
    """
    from qgis.PyQt.QtWidgets import QMessageBox
    from ...pyqt_version import Q_MESSAGEBOX_STD_BUTTON

    if error_title is None:
        error_title = tr_func("Cannot Save Map")

    # Get local layers
    local_layers = get_local_vector_layers()

    if not local_layers:
        return (False, [])

    # Check if any local layer has unsaved edits
    if check_unsaved_edits:
        is_modified = check_vector_layers_modified(local_layers)
        if is_modified:
            QMessageBox.warning(
                None,
                error_title,
                tr_func(
                    "Please save or discard your local layer edits before saving map."
                ),
            )
            return (False, [])

    # Ask user for confirmation
    convert_confirm = QMessageBox.question(
        None,
        tr_func("Convert Local Layers to Kumoy Layers"),
        tr_func(
            "There are {} local vector layers in the current project.\n"
            "Do you want to convert them to Kumoy layers?"
        ).format(len(local_layers)),
        Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
        Q_MESSAGEBOX_STD_BUTTON.Yes,
    )

    if convert_confirm != Q_MESSAGEBOX_STD_BUTTON.Yes:
        return (False, [])

    # Convert layers
    conversion_errors = convert_multiple_layers_to_kumoy(local_layers, project_id)
    return (True, conversion_errors)


def show_map_save_result(
    map_name: str,
    tr_func,
    user_confirmed_conversion: bool,
    conversion_errors: list[tuple[str, str]],
    action: str = "saved",
) -> None:
    """Show success or warning message after map save/create operation.

    Args:
        map_name: Name of the map
        tr_func: Translation function to use for messages
        user_confirmed_conversion: Whether user confirmed layer conversion
        conversion_errors: List of (layer_name, error_message) tuples
        action: Action performed ('saved' or 'created')
    """
    from qgis.PyQt.QtWidgets import QMessageBox
    from qgis.utils import iface

    if user_confirmed_conversion and conversion_errors:
        error_details = "\n".join(
            [f"• {layer_name}\n{error}\n" for layer_name, error in conversion_errors]
        )
        # Limit error details length
        msg_max_length = 1000
        if len(error_details) > msg_max_length:
            error_details = error_details[:msg_max_length] + "..."

        warning_title = (
            tr_func("Map Saved with Warnings")
            if action == "saved"
            else tr_func("Map Created with Warnings")
        )
        success_msg = tr_func(
            "Map '{}' has been {} successfully.\n\n"
            "Warning: {} layers could not be converted:\n\n{}"
        ).format(map_name, action, len(conversion_errors), error_details)

        QMessageBox.warning(None, warning_title, success_msg)
    else:
        success_msg = tr_func("Map '{}' has been {} successfully.").format(
            map_name, action
        )
        iface.messageBar().pushSuccess(tr_func("Success"), success_msg)


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
        progress_dialog.setValue(0)
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
                progress_dialog.setValue(int(progress))

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

            # Copy layer style from original layer
            _copy_layer_style(layer, kumoy_layer)

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
