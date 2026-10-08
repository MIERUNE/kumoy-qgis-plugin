from qgis.core import QgsRasterLayer

from .. import i18n
from . import api, constants


def raster_uri(raster: api.raster.KumoyRaster) -> str:
    return (
        f"project_id={raster.projectId};"
        f"raster_id={raster.id};"
        f"raster_name={raster.name};"
    )


def create_raster_layer(raster: api.raster.KumoyRaster) -> QgsRasterLayer:
    # The provider downloads the COG if it is not cached yet; a canceled or
    # failed download leaves the layer invalid
    layer = QgsRasterLayer(
        raster_uri(raster), raster.name, constants.RASTER_DATA_PROVIDER_KEY
    )
    if not layer.isValid():
        error_msg = layer.error().message() if layer.error() else "Unknown error"
        raise RuntimeError(
            i18n.tr("Failed to create Kumoy layer: {}").format(error_msg)
        )
    return layer
