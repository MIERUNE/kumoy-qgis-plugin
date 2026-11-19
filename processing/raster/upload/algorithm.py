import os
import tempfile
from typing import Any, Callable, Dict, List, Optional

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsMessageLog,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingParameterCrs,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterString,
    QgsRasterLayer,
)

from .... import i18n
from ....kumoy import api, constants, local_cache
from ....kumoy.tasks import Canceled
from ....kumoy.upload.presigned import (
    UploadCanceled,
    upload_file_to_presigned_put,
)
from ...base import KumoyUploadAlgorithm
from .cog import (
    SOURCE_UNREADABLE,
    CogConversionCanceled,
    convert_to_cog,
    read_source_crs_wkt,
)
from .materialize import RasterMaterializeCanceled, materialize_to_geotiff


def _resolve_assign_crs_wkt(layer: QgsRasterLayer, assign_crs) -> Optional[str]:
    """WKT of the CRS to assign, or None to keep the source's CRS.

    Rule: what the user sees in QGIS is what gets uploaded. A CRS set by hand
    in QGIS shows in ``layer.crs()`` but is not in the file, so compare with
    the file's embedded CRS:

    - file CRS equals layer CRS -> keep it
    - layer CRS differs (manual override in QGIS) -> assign the layer CRS
      (no reprojection)
    - file has no CRS -> the 'Assign CRS' parameter, else the layer CRS
      (including a manual one), else an error
    """
    if layer.providerType() == "gdal":
        # The file itself is converted: judge by its own CRS
        file_crs_wkt = read_source_crs_wkt(layer.source())
        if file_crs_wkt is SOURCE_UNREADABLE:
            # Undecidable; convert_to_cog opens the same path and reports it
            return None
        if file_crs_wkt is not None:
            layer_crs = layer.crs()
            file_crs = QgsCoordinateReferenceSystem.fromWkt(file_crs_wkt)
            if layer_crs.isValid() and layer_crs != file_crs:
                return layer_crs.toWkt()
            return None
    else:
        # Materializing writes layer.crs() (manual override included) into
        # the temporary GeoTIFF, so it becomes the converted file's CRS
        if layer.crs().isValid():
            return None

    # The file to convert has no CRS
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
    """Callback mapping 0-100 progress onto [start, end] of the whole run."""
    return lambda p: feedback.setProgress(start + int(p * (end - start) / 100))


def _temp_tif(prefix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".tif", prefix=prefix)
    os.close(fd)
    return path


def _remove_quietly(path: Optional[str]) -> None:
    if path is None or not os.path.exists(path):
        return
    try:
        os.remove(path)
    except OSError as e:
        # A leftover temp file is not worth failing the upload for
        QgsMessageLog.logMessage(
            f"Failed to remove temporary file {path}: {e}",
            constants.LOG_CATEGORY,
            Qgis.Warning,
        )


class UploadRasterAlgorithm(KumoyUploadAlgorithm):
    """Algorithm to convert a raster to COG and upload it to Kumoy backend"""

    GROUP_ID = "raster"
    RASTER_NAME = "RASTER_NAME"
    ASSIGN_CRS = "ASSIGN_CRS"

    def name(self) -> str:
        return "uploadraster"

    def displayName(self) -> str:
        return i18n.tr("Upload Raster Layer to Kumoy")

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
        ) + i18n.tr(
            "\n\nThe raster is converted to a Cloud Optimized GeoTIFF before "
            "upload, and the converted file must be {:,} bytes or less. If the "
            "name is left empty, the layer name is used, truncated to {} "
            "characters."
        ).format(
            constants.MAX_RASTER_UPLOAD_BYTES, constants.MAX_CHARACTERS_RASTER_NAME
        )

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_LAYER, i18n.tr("Input raster layer")
            )
        )
        self.add_project_parameters()
        self.addParameter(
            QgsProcessingParameterString(
                self.RASTER_NAME,
                i18n.tr("{} (max {} characters)").format(
                    i18n.tr("Raster layer name"), constants.MAX_CHARACTERS_RASTER_NAME
                ),
                defaultValue="",
                optional=True,
            )
        )
        # Only used when the source file has no CRS; otherwise the layer's CRS
        # (including a manual override in QGIS) wins
        self.addParameter(
            QgsProcessingParameterCrs(
                self.ASSIGN_CRS,
                i18n.tr("Assign CRS (only used when the source file has no CRS)"),
                optional=True,
            )
        )

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        layer = self.parameterAsRasterLayer(parameters, self.INPUT_LAYER, context)
        if layer is None:
            raise QgsProcessingException(i18n.tr("Invalid input layer"))

        project_id = self._resolve_project_id(parameters, context)
        raster_name = self.parameter_as_name(
            parameters,
            self.RASTER_NAME,
            context,
            layer.name(),
            constants.MAX_CHARACTERS_RASTER_NAME,
        )
        assign_crs_wkt = _resolve_assign_crs_wkt(
            layer, self.parameterAsCrs(parameters, self.ASSIGN_CRS, context)
        )
        # Before the conversion, which can take minutes
        self.check_destination(project_id, "raster")
        feedback.setProgress(5)

        materialized_path: Optional[str] = None
        cog_path: Optional[str] = None
        raster_id: Optional[str] = None
        try:
            # gdal layers are converted from their file. Others (e.g. virtual
            # rasters, which gdal cannot open) are rendered to a temporary
            # GeoTIFF first (5-35%); materialize rejects unsupported providers.
            src_path = layer.source()
            if layer.providerType() != "gdal":
                materialized_path = _temp_tif("kumoy_materialized_")
                feedback.pushInfo(i18n.tr("Rendering raster to a temporary file..."))
                materialize_to_geotiff(
                    layer,
                    materialized_path,
                    progress_callback=_progress_range(feedback, 5, 35),
                    is_canceled=feedback.isCanceled,
                )
                src_path = materialized_path

            cog_path = _temp_tif("kumoy_raster_")
            feedback.pushInfo(i18n.tr("Converting raster to COG..."))
            convert_to_cog(
                src_path=src_path,
                dst_path=cog_path,
                assign_crs_wkt=assign_crs_wkt,
                progress_callback=_progress_range(
                    feedback, 35 if materialized_path else 5, 70
                ),
                is_canceled=feedback.isCanceled,
            )
            if feedback.isCanceled():
                raise Canceled()

            cog_bytes = os.path.getsize(cog_path)
            if cog_bytes > constants.MAX_RASTER_UPLOAD_BYTES:
                raise QgsProcessingException(
                    i18n.tr(
                        "Cannot upload raster: the converted COG is {} bytes, "
                        "which exceeds the {} bytes limit."
                    ).format(f"{cog_bytes:,}", f"{constants.MAX_RASTER_UPLOAD_BYTES:,}")
                )

            upload = api.raster.create_raster(project_id, raster_name, cog_bytes)
            raster_id = upload.raster_id
            feedback.pushInfo(
                i18n.tr("Created raster '{}' with ID: {}").format(
                    raster_name, raster_id
                )
            )
            feedback.setProgress(72)

            # 72-99%: 100% of the callback means "all bytes written"; the
            # server still has to answer, so stay below 100 until it does
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
        except BaseException as e:
            if raster_id is not None:
                # Do not leave a raster without data behind (also on cancel)
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
            _remove_quietly(cog_path)
            if isinstance(
                e, (CogConversionCanceled, RasterMaterializeCanceled, UploadCanceled)
            ):
                raise Canceled() from None
            raise
        finally:
            _remove_quietly(materialized_path)

        # The uploaded COG is what the server serves: keep it as the local
        # cache so adding the layer does not download it again. Best effort.
        try:
            local_cache.raster.store(raster_id, cog_path)
        except OSError as e:
            QgsMessageLog.logMessage(
                f"Failed to store uploaded COG in local cache: {e}",
                constants.LOG_CATEGORY,
                Qgis.Warning,
            )
            _remove_quietly(cog_path)
        return {"RASTER_ID": raster_id}
