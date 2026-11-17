from qgis.core import QgsRasterLayer

from .. import i18n
from . import constants
from .api.models import Raster


def raster_uri(raster: Raster) -> str:
    return (
        f"project_id={raster.projectId};"
        f"raster_id={raster.id};"
        f"raster_name={raster.name};"
    )


def create_raster_layer(raster: Raster) -> QgsRasterLayer:
    """Layer for `raster`. Never blocks.

    When the COG is not cached yet the layer starts empty while it downloads
    in the background (see the provider); callers that want a complete layer
    cache first (ui/layers/raster.add_raster_to_map, download.download_raster).
    """
    layer = QgsRasterLayer(
        raster_uri(raster), raster.name, constants.RASTER_DATA_PROVIDER_KEY
    )
    if not layer.isValid():
        error_msg = layer.error().message() if layer.error() else "Unknown error"
        raise RuntimeError(
            i18n.tr("Failed to create Kumoy layer: {}").format(error_msg)
        )
    return layer
