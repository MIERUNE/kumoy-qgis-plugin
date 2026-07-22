import os
import tempfile
from typing import Any, Callable, Dict, List, Optional

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
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
from ...kumoy import api, constants, local_cache
from ...kumoy.api.error import format_api_error
from ...kumoy.get_token import get_token
from ...kumoy.settings_manager import get_settings
from ...kumoy.upload.presigned import (
    UploadCanceled,
    upload_file_to_presigned_put,
)
from .cog import (
    SOURCE_UNREADABLE,
    CogConversionCanceled,
    convert_to_cog,
    read_source_crs_wkt,
)
from .materialize import RasterMaterializeCanceled, materialize_to_geotiff


class _UserCanceled(Exception):
    """Internal exception used to short-circuit on user cancellation"""


def _resolve_assign_crs_wkt(layer: QgsRasterLayer, assign_crs) -> Optional[str]:
    """割り当てる CRS の WKT を返す。None は「ソースの CRS をそのまま保持」。

    原則は「ユーザーが QGIS 上で見ている CRS がそのままアップロードされる」。
    QGIS 上で手動設定した CRS は ``layer.crs()`` には現れるがファイルには
    焼き込まれていないため、ファイルに埋め込まれた CRS と突き合わせて判定する。

    - ファイルの CRS とレイヤ CRS が一致 → 再割り当てせずそのまま保持
    - レイヤ CRS がファイルの CRS と異なる（QGIS 上の手動上書き）→ レイヤ CRS
      を割り当てる（再投影はしない）
    - ファイルに CRS が無い → 「Assign CRS」パラメータ → レイヤの CRS
      （手動設定を含む）→ 無ければエラー
    """
    if layer.providerType() == "gdal":
        # 元ファイルをそのまま COG 変換へ渡す経路。ファイル自体の CRS で判定。
        file_crs_wkt = read_source_crs_wkt(layer.source())
        if file_crs_wkt is SOURCE_UNREADABLE:
            # 判定不能。エラー報告は同じパスを開く convert_to_cog に任せる。
            return None
        if file_crs_wkt is not None:
            layer_crs = layer.crs()
            file_crs = QgsCoordinateReferenceSystem.fromWkt(file_crs_wkt)
            if layer_crs.isValid() and layer_crs != file_crs:
                return layer_crs.toWkt()
            return None
    else:
        # 実体化経路は layer.crs() を一時 GeoTIFF に書き込むので、手動上書きを
        # 含むレイヤ CRS がそのまま変換対象ファイルの CRS になる。
        if layer.crs().isValid():
            return None

    # ここまで来たら変換対象ファイルに CRS が無い。
    if assign_crs is not None and assign_crs.isValid():
        return assign_crs.toWkt()
    if layer.crs().isValid():
        return layer.crs().toWkt()
    raise QgsProcessingException(
        i18n.tr(
            "The input layer has no coordinate reference system. "
            "Please set one in the 'Assign CRS' field before uploading."
        )
    )


def _progress_range(
    feedback: QgsProcessingFeedback, start: int, end: int
) -> Callable[[float], None]:
    """0-100 の進捗を全体進捗の [start, end] 区間へ写像するコールバックを返す"""
    return lambda p: feedback.setProgress(start + int(p * (end - start) / 100))


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
            "Upload a raster layer to the Kumoy cloud.\n\n"
            "You can upload:\n"
            "- Raster files such as GeoTIFF\n"
            "- QGIS virtual rasters (e.g. a virtual output of the raster "
            "calculator)\n\n"
            "Web-based layers such as WMS, WCS, or XYZ tiles cannot be uploaded "
            "because they don't contain the original pixel data.\n\n"
            "No reprojection is applied: the original pixel values are "
            "preserved. The CRS set on the layer in QGIS is used: if it differs "
            "from the CRS embedded in the source file (a manual override), the "
            "layer's CRS is assigned without reprojecting. If the source file "
            "has no CRS, the 'Assign CRS' field or the layer's CRS is "
            "assigned.\n\n"
            "The input dropdown lists raster layers in your current project. "
            "If no project is open, it will be empty."
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
                # Organizations scheduled for deletion are unusable; their
                # project APIs return not found
                if org.scheduledDeletionAt:
                    continue
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

        # 元ファイルに CRS が無いときだけ使う。未設定ならレイヤの CRS
        # （QGIS 上での手動設定を含む）にフォールバックする。
        self.addParameter(
            QgsProcessingParameterCrs(
                self.ASSIGN_CRS,
                i18n.tr("Assign CRS (only used when the source file has no CRS)"),
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

    def _validate_role_and_quota(self, project_id: str) -> None:
        """Fail fast before the expensive COG conversion.

        The server enforces both anyway (403/429 on create_raster), but that
        happens after conversion; checking here saves the user the wait.
        """
        project = api.project.get_project(project_id)
        organization = api.organization.get_organization(project.team.organizationId)

        if project.role not in ["ADMIN", "OWNER"]:
            raise QgsProcessingException(
                i18n.tr("You do not have permission to upload rasters to this project.")
            )

        plan_limits = api.plan.get_plan_limits(
            organization.subscriptionPlan, organization.storageUnits
        )
        # maxRasters is the org-wide cap; usage.rasters is the total across
        # all projects.
        if organization.usage.rasters >= plan_limits.maxRasters:
            raise QgsProcessingException(
                i18n.tr(
                    "Cannot upload raster: your organization has reached your "
                    "plan's limit of {} rasters. Delete an existing raster or "
                    "upgrade your plan to add more."
                ).format(plan_limits.maxRasters)
            )

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
        materialized_path: Optional[str] = None

        try:
            feedback.setProgress(0)
            self._raise_if_canceled(feedback)

            layer = self.parameterAsRasterLayer(parameters, self.INPUT_LAYER, context)
            if layer is None:
                raise QgsProcessingException(i18n.tr("Invalid input layer"))

            project_id, raster_name = self._resolve_project_and_name(
                parameters, context, layer
            )
            assign_crs_wkt = _resolve_assign_crs_wkt(
                layer, self.parameterAsCrs(parameters, self.ASSIGN_CRS, context)
            )
            self._validate_role_and_quota(project_id)

            self._raise_if_canceled(feedback)
            feedback.setProgress(5)

            # gdal プロバイダは元ファイルのパスをそのまま COG 変換へ渡す。
            # それ以外（gdal.Open できない仮想ラスタ等）は一時 GeoTIFF に実体化して
            # から変換する（進捗 5-35%）。非対応プロバイダは materialize が弾く。
            src_path = layer.source()
            if layer.providerType() != "gdal":
                fd, materialized_path = tempfile.mkstemp(
                    suffix=".tif", prefix="kumoy_materialized_"
                )
                os.close(fd)
                feedback.pushInfo(i18n.tr("Rendering raster to a temporary file..."))
                materialize_to_geotiff(
                    layer,
                    materialized_path,
                    progress_callback=_progress_range(feedback, 5, 35),
                    is_canceled=feedback.isCanceled,
                )
                src_path = materialized_path
                self._raise_if_canceled(feedback)

            # COG へ変換（再投影なし）。実体化ありなら進捗 35-70%、なしなら 5-70%。
            cog_start = 35 if materialized_path else 5
            fd, cog_path = tempfile.mkstemp(suffix=".tif", prefix="kumoy_raster_")
            os.close(fd)
            feedback.pushInfo(i18n.tr("Converting raster to COG..."))
            convert_to_cog(
                src_path=src_path,
                dst_path=cog_path,
                assign_crs_wkt=assign_crs_wkt,
                progress_callback=_progress_range(feedback, cog_start, 70),
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

            # メタデータ登録 + presigned PUT URL 取得。
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

            # COG を S3 へストリーミングアップロード。進捗 72-99%。
            # upload_url は署名済みの絶対 URL（S3/rustfs エンドポイント直指定）。
            # コールバックの 100% は「全バイトをソケットへ書き終えた」段階で、
            # その後もサーバの応答待ちが残るため、完了(リターン)まで 99% で止める。
            feedback.pushInfo(i18n.tr("Uploading COG..."))
            waiting_notified = False

            def on_upload_progress(p: float) -> None:
                nonlocal waiting_notified
                feedback.setProgress(72 + int(p * 0.27))
                if p >= 100.0 and not waiting_notified:
                    waiting_notified = True
                    feedback.pushInfo(i18n.tr("Waiting for server response..."))

            upload_file_to_presigned_put(
                url=upload.upload_url,
                file_path=cog_path,
                content_type="image/tiff",
                progress_callback=on_upload_progress,
                is_canceled=feedback.isCanceled,
            )
            feedback.setProgress(100)
            feedback.pushInfo(i18n.tr("Upload complete"))

            # アップロードした COG は S3 上の実体と同一なので、そのままローカル
            # キャッシュへ取り込み、レイヤ追加時の再ダウンロードを省く。
            # 失敗してもアップロード自体は成功しているので best-effort。
            try:
                local_cache.raster.store(raster_id, cog_path)
                cog_path = None  # store が消費済み。finally での削除対象から外す
            except OSError as cache_error:
                QgsMessageLog.logMessage(
                    f"Failed to store uploaded COG in local cache: {cache_error}",
                    constants.LOG_CATEGORY,
                    Qgis.Warning,
                )

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

            if isinstance(
                e,
                (
                    _UserCanceled,
                    CogConversionCanceled,
                    UploadCanceled,
                    RasterMaterializeCanceled,
                ),
            ):
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

            raise

        finally:
            for path in (materialized_path, cog_path):
                if path is not None and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError as cleanup_error:
                        # 一時ファイル削除の失敗はログだけ残す
                        QgsMessageLog.logMessage(
                            f"Failed to remove temporary file {path}: {cleanup_error}",
                            constants.LOG_CATEGORY,
                            Qgis.Warning,
                        )
