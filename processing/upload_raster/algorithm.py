import os
import tempfile
from typing import Any, Dict, List, Optional

from qgis.core import (
    Qgis,
    QgsMessageLog,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingParameterCrs,
    QgsProcessingParameterEnum,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterString,
    QgsRasterLayer,
)
from qgis.utils import iface

from ... import i18n
from ...kumoy import api, constants
from ...kumoy.api.error import format_api_error
from ...kumoy.get_token import get_token
from ...kumoy.settings_manager import get_settings
from ...kumoy.upload.presigned import (
    UploadCanceled,
    upload_file_to_presigned_post,
)
from .cog import CogConversionCanceled, convert_to_cog


class _UserCanceled(Exception):
    """Internal exception used to short-circuit on user cancellation"""


class UploadRasterAlgorithm(QgsProcessingAlgorithm):
    """Algorithm to convert a raster to COG and upload it to Kumoy backend"""

    INPUT_LAYER: str = "INPUT"
    KUMOY_PROJECT: str = "PROJECT"
    RASTER_NAME: str = "RASTER_NAME"
    ASSIGN_CRS: str = "ASSIGN_CRS"

    project_ids: List[str]

    def __init__(self) -> None:
        super().__init__()
        self.project_ids = []

    def createInstance(self) -> "UploadRasterAlgorithm":
        return UploadRasterAlgorithm()

    def name(self) -> str:
        return "uploadraster"

    def displayName(self) -> str:
        return i18n.tr("Upload Raster Layer to Kumoy")

    def group(self):
        return None

    def groupId(self):
        return None

    def helpUrl(self) -> str:
        return constants.DOCUMENTATION_URL

    def shortHelpString(self) -> str:
        return i18n.tr(
            "Convert a raster layer to Cloud Optimized GeoTIFF (COG) and upload "
            "it to the Kumoy cloud.\n\n"
            "The raster is not reprojected: its original CRS and pixel values are "
            "preserved. If the layer has no CRS, set one in the 'Assign CRS' field.\n\n"
            "The Input Raster Layer dropdown shows raster layers in your current map. "
            "If no map is open, it will be empty."
        )

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        project_options: List[str] = []
        self.project_ids = []

        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_LAYER,
                i18n.tr("Input raster layer"),
            )
        )

        try:
            if get_token() is None:
                # 未ログイン
                return

            organizations = api.organization.get_organizations()
            for org in organizations:
                projects = api.project.get_projects_by_organization(org.id)
                for project in projects:
                    project_options.append(f"{org.name} / {project.name}")
                    self.project_ids.append(project.id)

        except Exception as e:
            msg = i18n.tr("Error Initializing Processing: {}").format(
                format_api_error(e)
            )
            QgsMessageLog.logMessage(msg, constants.LOG_CATEGORY, Qgis.Critical)
            iface.messageBar().pushMessage(
                constants.PLUGIN_NAME, msg, level=Qgis.Critical, duration=10
            )
            return

        default_project_index = 0
        selected_project_id = get_settings().selected_project_id
        if selected_project_id and self.project_ids:
            for idx, pid in enumerate(self.project_ids):
                if pid == selected_project_id:
                    default_project_index = idx
                    break

        self.addParameter(
            QgsProcessingParameterEnum(
                self.KUMOY_PROJECT,
                i18n.tr("Destination project"),
                options=project_options,
                allowMultiple=False,
                optional=False,
                defaultValue=default_project_index,
            )
        )

        self.addParameter(
            QgsProcessingParameterString(
                self.RASTER_NAME,
                i18n.tr("Raster layer name"),
                defaultValue="",
                optional=True,
            )
        )

        # 元ラスタに CRS が無いときだけ使う。未設定なら元の CRS を保持する。
        self.addParameter(
            QgsProcessingParameterCrs(
                self.ASSIGN_CRS,
                i18n.tr("Assign CRS (only used when the layer has no CRS)"),
                optional=True,
            )
        )

    def _resolve_project_and_name(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        layer: QgsRasterLayer,
    ):
        project_index = self.parameterAsEnum(parameters, self.KUMOY_PROJECT, context)
        if project_index < 0 or project_index >= len(self.project_ids):
            raise QgsProcessingException(
                i18n.tr("Invalid destination project selection.")
            )
        project_id = self.project_ids[project_index]

        raster_name = self.parameterAsString(parameters, self.RASTER_NAME, context)
        if not raster_name:
            raster_name = layer.name()[: constants.MAX_CHARACTERS_VECTOR_NAME]

        return project_id, raster_name

    def _resolve_assign_crs(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        layer: QgsRasterLayer,
    ) -> Optional[str]:
        """Return CRS WKT to assign, or None to keep the layer's existing CRS.

        Raises when the layer has no CRS and the user did not provide one.
        """
        if layer.crs().isValid():
            return None

        assign_crs = self.parameterAsCrs(parameters, self.ASSIGN_CRS, context)
        if assign_crs is None or not assign_crs.isValid():
            raise QgsProcessingException(
                i18n.tr(
                    "The input layer has no coordinate reference system. "
                    "Please set one in the 'Assign CRS' field before uploading."
                )
            )
        return assign_crs.toWkt()

    def _raise_if_canceled(self, feedback: QgsProcessingFeedback) -> None:
        if feedback.isCanceled():
            raise _UserCanceled()

    def processAlgorithm(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        raster_id: Optional[str] = None
        cog_path: Optional[str] = None

        try:
            feedback.setProgress(0)
            self._raise_if_canceled(feedback)

            layer = self.parameterAsRasterLayer(parameters, self.INPUT_LAYER, context)
            if layer is None:
                raise QgsProcessingException(i18n.tr("Invalid input layer"))

            project_id, raster_name = self._resolve_project_and_name(
                parameters, context, layer
            )
            assign_crs_wkt = self._resolve_assign_crs(parameters, context, layer)

            self._raise_if_canceled(feedback)
            feedback.setProgress(5)

            # COG へ変換（再投影なし）。進捗 5-70%。
            fd, cog_path = tempfile.mkstemp(suffix=".tif", prefix="kumoy_raster_")
            os.close(fd)
            feedback.pushInfo(i18n.tr("Converting raster to COG..."))
            convert_to_cog(
                src_path=layer.source(),
                dst_path=cog_path,
                assign_crs_wkt=assign_crs_wkt,
                progress_callback=lambda p: feedback.setProgress(5 + int(p * 0.65)),
                is_canceled=feedback.isCanceled,
            )
            feedback.setProgress(70)
            self._raise_if_canceled(feedback)

            cog_bytes = os.path.getsize(cog_path)
            if cog_bytes > constants.MAX_RASTER_UPLOAD_BYTES:
                raise QgsProcessingException(
                    i18n.tr(
                        "Cannot upload raster: the converted COG is {} bytes, "
                        "which exceeds the {} bytes limit."
                    ).format(f"{cog_bytes:,}", f"{constants.MAX_RASTER_UPLOAD_BYTES:,}")
                )

            # メタデータ登録 + presigned POST 取得。
            upload = api.raster.create_raster(
                project_id=project_id, name=raster_name, bytes=cog_bytes
            )
            raster_id = upload.raster_id
            feedback.pushInfo(
                i18n.tr("Created raster '{}' with ID: {}").format(
                    raster_name, raster_id
                )
            )
            feedback.setProgress(72)
            self._raise_if_canceled(feedback)

            # COG を S3 へ presigned POST でストリーミングアップロード。進捗 72-100%。
            # upload_fields の署名フィールドを順序通りに並べ、ファイルは最後に送る。
            feedback.pushInfo(i18n.tr("Uploading COG..."))
            upload_file_to_presigned_post(
                url=upload.upload_url,
                fields=upload.upload_fields,
                file_path=cog_path,
                progress_callback=lambda p: feedback.setProgress(72 + int(p * 0.28)),
                is_canceled=feedback.isCanceled,
            )
            feedback.setProgress(100)
            feedback.pushInfo(i18n.tr("Upload complete"))

            return {"RASTER_ID": raster_id}

        except Exception as e:
            # 登録済みで以降に失敗したら、サーバ側の不完全なラスタを消す。
            if raster_id is not None:
                try:
                    api.raster.delete_raster(raster_id)
                    feedback.pushInfo(
                        i18n.tr("Cleaned up incomplete raster due to upload failure")
                    )
                except Exception as cleanup_error:
                    feedback.reportError(
                        i18n.tr("Failed to clean up incomplete raster: {}").format(
                            str(cleanup_error)
                        )
                    )

            if isinstance(e, (_UserCanceled, CogConversionCanceled, UploadCanceled)):
                return {}

            if isinstance(e, api.error.QuotaExceededError):
                QgsMessageLog.logMessage(
                    format_api_error(e), constants.LOG_CATEGORY, Qgis.Critical
                )
                raise QgsProcessingException(
                    i18n.tr(
                        "Cannot upload raster: your organization has reached your "
                        "plan's limit. Delete an existing item or upgrade your "
                        "plan to add more."
                    )
                ) from None

            if isinstance(e, api.error.UnauthorizedError):
                QgsMessageLog.logMessage(
                    format_api_error(e), constants.LOG_CATEGORY, Qgis.Critical
                )
                raise QgsProcessingException(
                    i18n.tr(
                        "You do not have permission to upload rasters to this project."
                    )
                ) from None

            raise e

        finally:
            if cog_path is not None and os.path.exists(cog_path):
                try:
                    os.remove(cog_path)
                except OSError:
                    pass
