"""Render a QGIS virtual raster to a GeoTIFF that GDAL can open.

Virtual rasters (e.g. a raster calculator's virtual output) have no file for
gdal.Open, so their pixels are written to a temporary GeoTIFF first. The COG
driver only supports CreateCopy, which QgsRasterFileWriter (Create based)
cannot use, hence the two steps: GeoTIFF here, then convert_to_cog().

WMS/WCS and other providers are refused: uploads take only rasters whose
original pixels are local.
"""

from typing import Callable, Optional

from qgis.core import (
    QgsCoordinateTransformContext,
    QgsRasterBlockFeedback,
    QgsRasterFileWriter,
    QgsRasterLayer,
    QgsRasterPipe,
)

from .... import i18n
from ....kumoy.tasks import Canceled


class RasterMaterializeCanceled(Canceled):
    """The `is_canceled` callback asked to stop."""


def materialize_to_geotiff(
    layer: QgsRasterLayer,
    dst_path: str,
    progress_callback: Optional[Callable[[float], None]] = None,
    is_canceled: Optional[Callable[[], bool]] = None,
) -> None:
    """Write the pixels of `layer` (provider `virtualraster`) to `dst_path`.

    Same conventions as convert_to_cog(): progress 0-100, cancel by polling
    `is_canceled`, `dst_path` is the caller's to create and delete.
    Raises RasterMaterializeCanceled, or Exception for other providers or
    when QGIS fails to write.
    """
    if layer.providerType() != "virtualraster":
        raise Exception(
            i18n.tr(
                "This raster cannot be uploaded because it uses an unsupported "
                "source type ({}). Only file-based rasters and QGIS virtual "
                "rasters are supported."
            ).format(layer.providerType())
        )

    provider = layer.dataProvider()
    if provider is None or not provider.isValid():
        raise Exception(i18n.tr("The input raster layer has no readable data source."))

    if is_canceled is not None and is_canceled():
        raise RasterMaterializeCanceled()

    # The pipe takes ownership of what it is given, hence the clone
    clone = provider.clone()
    pipe = QgsRasterPipe()
    if not pipe.set(clone):
        raise Exception(i18n.tr("Failed to prepare the raster for rendering."))

    # writeRaster reports through a feedback object; poll is_canceled on each
    # progress step and turn it into feedback.cancel()
    feedback = QgsRasterBlockFeedback()

    def on_progress(percent: float) -> None:
        if is_canceled is not None and is_canceled():
            feedback.cancel()
        if progress_callback is not None:
            progress_callback(percent)

    feedback.progressChanged.connect(on_progress)

    writer = QgsRasterFileWriter(dst_path)
    writer.setOutputFormat("GTiff")
    # Same CRS in and out, so an empty transform context is enough
    err = writer.writeRaster(
        pipe,
        clone.xSize(),
        clone.ySize(),
        clone.extent(),
        clone.crs(),
        QgsCoordinateTransformContext(),
        feedback,
    )

    if feedback.isCanceled():
        raise RasterMaterializeCanceled()
    if err != QgsRasterFileWriter.NoError:
        raise Exception(
            i18n.tr("QGIS failed to render the raster to a file (error {}).").format(
                err
            )
        )
