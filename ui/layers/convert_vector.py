from qgis.core import (
    Qgis,
    QgsMessageLog,
    QgsProject,
    QgsVectorLayer,
    QgsProcessingContext,
    QgsProcessingFeedback,
)
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QInputDialog, QMessageBox, QProgressDialog
from qgis.PyQt.QtCore import Qt
from qgis.utils import iface
import processing

from ...kumoy import constants
from ...kumoy.api import organization, project, vector
from ...kumoy.api.error import format_api_error
from ...settings_manager import get_settings


def tr(message):
    return QCoreApplication.translate("ConvertVectorAction", message)


def convert_layer_to_kumoy(layer: QgsVectorLayer):
    """Convert a vector layer to Kumoy"""
    progress_dialog = None

    try:
        # Get organization and projects
        settings = get_settings()
        if not settings.id_token:
            QMessageBox.warning(None, tr("Not Logged In"), tr("Please log in first."))
            return

        # Get all organizations
        organizations = organization.get_organizations()
        if not organizations:
            QMessageBox.warning(
                None,
                tr("No Organizations"),
                tr("You don't have access to any organizations."),
            )
            return

        # Get ALL projects from ALL organizations (same order as in the algorithm)
        all_projects = []
        project_display_names = []

        for org in organizations:
            org_projects = project.get_projects_by_organization(org.id)
            for proj in org_projects:
                all_projects.append(proj)
                # Display format: "Organization / Project"
                project_display_names.append(f"{org.name} / {proj.name}")

        if not all_projects:
            QMessageBox.warning(
                None,
                tr("No Projects"),
                tr("No projects found in any organization."),
            )
            return

        # Find default project index based on selected_project_id
        default_index = 0
        selected_project_id = settings.selected_project_id
        if selected_project_id:
            for idx, proj in enumerate(all_projects):
                if proj.id == selected_project_id:
                    default_index = idx
                    break

        # Let user select project
        project_name, ok = QInputDialog.getItem(
            None,
            tr("Select Project"),
            tr("Select a project to upload to:"),
            project_display_names,
            default_index,
            False,
        )

        if not ok:
            return

        # Find the selected project INDEX
        selected_index = project_display_names.index(project_name)

        # Use layer name as vector name
        vector_name = layer.name()

        # Create progress dialog
        progress_dialog = QProgressDialog(
            tr("Uploading layer '{}'...").format(vector_name),
            tr("Cancel"),
            0,
            100,
            iface.mainWindow(),
        )
        progress_dialog.setWindowTitle(tr("Kumoy Upload"))
        progress_dialog.setWindowModality(Qt.ApplicationModal)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setValue(10)
        progress_dialog.show()

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

        # Run the upload algorithm
        result = processing.run(
            "kumoy:uploadvector",
            {
                "INPUT": layer,
                "PROJECT": selected_index,
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
            return

        if not result or "VECTOR_ID" not in result:
            raise Exception(tr("Upload failed - no vector ID returned"))

        vector_id = result["VECTOR_ID"]

        # Close progress dialog BEFORE creating the Kumoy layer
        progress_dialog.close()
        progress_dialog = None

        # Show message that upload is complete
        iface.messageBar().pushMessage(
            constants.PLUGIN_NAME,
            tr("Upload complete, adding layer to map..."),
            level=Qgis.Info,
            duration=2,
        )

        # Get updated vector details
        vector_detail = vector.get_vector(vector_id)

        # Create Kumoy layer URI
        vector_uri = f"project_id={vector_detail.projectId};vector_id={vector_detail.id};vector_name={vector_detail.name};vector_type={vector_detail.type};"

        # Create the layer
        kumoy_layer = QgsVectorLayer(
            vector_uri, vector_detail.name, constants.DATA_PROVIDER_KEY
        )

        if kumoy_layer.isValid():
            # Configure kumoy_id as read-only
            field_idx = kumoy_layer.fields().indexOf("kumoy_id")
            if field_idx >= 0:
                config = kumoy_layer.editFormConfig()
                config.setReadOnly(field_idx, True)
                kumoy_layer.setEditFormConfig(config)

            # Copy layer styling from original
            kumoy_layer.setRenderer(layer.renderer().clone())

            # Get original layer position in legend
            root = QgsProject.instance().layerTreeRoot()
            original_layer_node = root.findLayer(layer.id())

            if original_layer_node:
                parent_node = original_layer_node.parent()
                # Get the index position of the original layer
                index = parent_node.children().index(original_layer_node)

                # Remove original layer from project
                QgsProject.instance().removeMapLayer(layer.id())

                # Add new Kumoy layer at the SAME index position
                QgsProject.instance().addMapLayer(kumoy_layer, False)
                parent_node.insertLayer(index, kumoy_layer)
            else:
                # Fallback: just add to root if original node not found
                QgsProject.instance().removeMapLayer(layer.id())
                QgsProject.instance().addMapLayer(kumoy_layer)

            iface.messageBar().pushMessage(
                constants.PLUGIN_NAME,
                tr("Layer '{}' converted to Kumoy successfully!").format(vector_name),
                level=Qgis.Success,
                duration=2,
            )
        else:
            error_msg = (
                kumoy_layer.error().message()
                if kumoy_layer.error()
                else "Unknown error"
            )
            raise Exception(tr("Failed to create Kumoy layer: {}").format(error_msg))

    except Exception as e:
        if progress_dialog:
            progress_dialog.close()

        QgsMessageLog.logMessage(
            f"Error converting layer: {str(e)}",
            constants.LOG_CATEGORY,
            Qgis.Critical,
        )
        iface.messageBar().pushMessage(
            constants.PLUGIN_NAME,
            tr("Error: {}").format(format_api_error(e)),
            level=Qgis.Critical,
            duration=10,
        )
