from typing import Any, Dict, Optional, Set

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsFields,
    QgsMessageLog,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterField,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QMessageBox,
)
from qgis.utils import iface

import processing

from ...kumoy import api, constants
from ...kumoy.api.error import format_api_error
from ...kumoy.get_token import get_token
from ...sentry import capture_exception
from ...settings_manager import get_settings
from ...ui.browser.vector import VectorItem


class _UserCanceled(Exception):
    """Internal exception used to short-circuit on user cancellation"""


class ConvertVectorAlgorithm(QgsProcessingAlgorithm):
    """Algorithm to convert vector layer to Kumoy vector layer"""

    INPUT_LAYER: str = "INPUT"
    KUMOY_PROJECT: str = "PROJECT"
    VECTOR_NAME: str = "VECTOR_NAME"
    SELECTED_FIELDS: str = "SELECTED_FIELDS"
    OUTPUT: str = "OUTPUT"  # Hidden output for internal processing

    project_map: Dict[str, str] = {}

    def tr(self, string: str) -> str:
        """Translate string"""
        return QCoreApplication.translate("ConvertVectorAlgorithm", string)

    def createInstance(self) -> "ConvertVectorAlgorithm":
        """Create new instance of algorithm"""
        return ConvertVectorAlgorithm()

    def name(self) -> str:
        """Algorithm name"""
        return "convertvector"

    def displayName(self) -> str:
        """Algorithm display name"""
        return self.tr("Convert Vector Layer to Kumoy Layer")

    def group(self):
        return None

    def groupId(self):
        return None

    def shortHelpString(self) -> str:
        """Short help string"""
        return self.tr(
            "Input local layer will be replaced by its converted Kumoy vector layer. "
        )

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        """Initialize algorithm parameters"""
        project_options = []
        self.project_map = {}

        # Input vector layer
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_LAYER,
                self.tr("Input local vector layer"),
                [QgsProcessing.TypeVectorAnyGeometry],
            )
        )

        try:
            if get_token() is None:
                # 未ログイン
                return

            # Get all organizations first
            organizations = api.organization.get_organizations()
            project_options = []
            project_ids = []

            # Get projects for each organization
            for org in organizations:
                projects = api.project.get_projects_by_organization(org.id)
                for project in projects:
                    project_options.append(f"{org.name} / {project.name}")
                    project_ids.append(project.id)

        except Exception as e:
            msg = self.tr("Error Initializing Processing: {}").format(
                format_api_error(e)
            )
            QgsMessageLog.logMessage(msg, constants.LOG_CATEGORY, Qgis.Critical)
            iface.messageBar().pushMessage(
                constants.PLUGIN_NAME, msg, level=Qgis.Critical, duration=10
            )
            return

        self.project_map = dict(zip(project_options, project_ids))
        default_project_index = 0
        selected_project_id = get_settings().selected_project_id
        if selected_project_id and self.project_map:
            # Find the index for the selected project ID
            for idx, (_, pid) in enumerate(self.project_map.items()):
                if pid == selected_project_id:
                    default_project_index = idx
                    break

        # Project selection
        self.addParameter(
            QgsProcessingParameterEnum(
                self.KUMOY_PROJECT,
                self.tr("Destination project"),
                options=project_options,
                allowMultiple=False,
                optional=False,
                defaultValue=default_project_index,
            )
        )

        # Field selection
        self.addParameter(
            QgsProcessingParameterField(
                self.SELECTED_FIELDS,
                self.tr("Attributes to upload"),
                parentLayerParameterName=self.INPUT_LAYER,
                type=QgsProcessingParameterField.Any,
                optional=True,
                allowMultiple=True,
                defaultValue=[],
            )
        )

        # Vector name
        self.addParameter(
            QgsProcessingParameterString(
                self.VECTOR_NAME,
                self.tr("Vector layer name"),
                defaultValue="",
                optional=True,
            )
        )

        # Hidden output parameter for internal processing
        param = QgsProcessingParameterFeatureSink(
            self.OUTPUT,
            self.tr("Temporary output"),
            type=QgsProcessing.TypeVectorAnyGeometry,
            createByDefault=True,
            defaultValue="TEMPORARY_OUTPUT",
            optional=True,
        )
        param.setFlags(param.flags() | QgsProcessingParameterFeatureSink.FlagHidden)
        self.addParameter(param)

    def _raise_if_canceled(self, feedback: QgsProcessingFeedback) -> None:
        """Raise internal cancel marker to unwind quickly without reporting error."""
        if feedback.isCanceled():
            raise _UserCanceled()

    def processAlgorithm(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        """Process the algorithm"""
        vector = None

        try:
            self._raise_if_canceled(feedback)

            # Upload the layer using the upload algorithm
            upload_params = {
                "INPUT": parameters[self.INPUT_LAYER],
                "PROJECT": parameters[self.KUMOY_PROJECT],
                "SELECTED_FIELDS": parameters[self.SELECTED_FIELDS],
                "VECTOR_NAME": parameters[self.VECTOR_NAME],
            }

            feedback.pushInfo(self.tr("Step 1: Uploading vector layer..."))

            result = processing.run(
                "kumoy:uploadvector",
                upload_params,
                context=context,
                feedback=feedback,
                is_child_algorithm=True,
            )

            vector_id = result.get("VECTOR_ID")

            self._raise_if_canceled(feedback)

            feedback.pushInfo(self.tr("Step 2: Import uploaded vector layer..."))

            try:
                # memo: Kumoy Provider内でAPIはコールされるが、データの存在確認のため、Vectorを取得しておく
                vector = api.vector.get_vector(vector_id)

            except Exception as e:
                msg = self.tr("Error fetching vector: {}").format(format_api_error(e))
                QgsMessageLog.logMessage(msg, constants.LOG_CATEGORY, Qgis.Critical)
                QMessageBox.critical(None, self.tr("Error"), msg)
                return
            layer = self._add_vector_to_map(vector, feedback)

            if layer:
                feedback.pushInfo(
                    self.tr("Vector layer '{}' added to map successfully").format(
                        layer.name()
                    )
                )
            else:
                feedback.reportError(
                    self.tr("Failed to add vector layer '{}' to map").format(
                        layer.name()
                    )
                )

            self._raise_if_canceled(feedback)

        except Exception as e:
            # If vector was created but upload failed, delete it
            if vector is not None:
                try:
                    api.vector.delete_vector(vector.id)
                    feedback.pushInfo(
                        self.tr(
                            "Cleaned up incomplete vector layer due to upload failure"
                        )
                    )
                except Exception as cleanup_error:
                    feedback.reportError(
                        self.tr(
                            "Failed to clean up incomplete vector layer: {}"
                        ).format(str(cleanup_error))
                    )

            if not isinstance(e, _UserCanceled):
                capture_exception(
                    e,
                    {
                        "algorithm": "ConvertVectorAlgorithm",
                        "project_id": project_id if "project_id" in locals() else "",
                        "vector_name": vector_name if "vector_name" in locals() else "",
                    },
                )
                # Re-raise the original exception
                raise e
            else:
                return {}

    def _add_vector_to_map(self, vector, feedback) -> None:
        """Add vector layer to QGIS map"""

        vector_uri = f"project_id={vector.projectId};vector_id={vector.id};vector_name={vector.name};vector_type={vector.type};"
        feedback.pushInfo(vector_uri)

        # IMPORTANT: Process events before creating layer
        QCoreApplication.processEvents()

        try:
            # Create layer with explicit provider options
            layer = QgsVectorLayer(
                vector_uri,
                vector.name,
                constants.DATA_PROVIDER_KEY,
                QgsVectorLayer.LayerOptions(
                    loadDefaultStyle=False, readExtentFromXml=False
                ),
            )

            # Process events after creation
            QCoreApplication.processEvents()

            feedback.pushInfo(self.tr("Layer object created, checking validity..."))

        except Exception as e:
            feedback.reportError(self.tr("Exception creating layer: {}").format(str(e)))
            QgsMessageLog.logMessage(
                f"Exception creating layer: {str(e)}",
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )
            return None
        if layer.isValid():
            # kumoy_idをread-onlyに設定
            field_idx = layer.fields().indexOf("kumoy_id")
            # フィールド設定で読み取り専用を設定
            if layer.fields().fieldOrigin(field_idx) == QgsFields.OriginProvider:
                # プロバイダーフィールドの場合
                config = layer.editFormConfig()
                config.setReadOnly(field_idx, True)
                layer.setEditFormConfig(config)

            # Add layer to map
            QgsProject.instance().addMapLayer(layer)
        else:
            QgsMessageLog.logMessage(
                f"Layer is invalid: {vector_uri}",
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )

        return layer if layer.isValid() else None
