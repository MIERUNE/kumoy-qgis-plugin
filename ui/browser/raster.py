from typing import Dict, List

from qgis.PyQt.QtWidgets import QAction, QMenu

from ... import i18n
from ...kumoy import api, constants, local_cache, raster_layer
from ..icons import BROWSER_RASTER_ICON
from ..layers.raster import add_raster_to_map
from .utils import ResourceItem, ResourceRoot


class RasterItem(ResourceItem):
    """A raster (COG). The file is cached locally and downloaded on first use."""

    PROVIDER_KEY = constants.RASTER_DATA_PROVIDER_KEY
    ID_KEY = "raster_id"
    LAYER_TYPE = "raster"
    MAX_NAME = constants.MAX_CHARACTERS_RASTER_NAME
    MAX_ATTRIBUTION = constants.MAX_CHARACTERS_RASTER_ATTRIBUTION
    CACHE = local_cache.raster

    def __init__(self, parent, path: str, raster: api.models.Raster, role: str):
        super().__init__(parent, path, raster, role, BROWSER_RASTER_ICON)

    @property
    def raster(self) -> api.models.Raster:
        return self.resource

    @staticmethod
    def api_update(raster_id: str, name: str, attribution: str):
        return api.raster.update_raster(raster_id, name=name, attribution=attribution)

    @staticmethod
    def api_delete(raster_id: str) -> None:
        api.raster.delete_raster(raster_id)

    @staticmethod
    def layer_uri(raster) -> str:
        return raster_layer.raster_uri(raster)

    def create_layer(self):
        # The COG downloads in the background first; the helper adds the layer
        # itself once it is cached, so there is nothing to return here
        add_raster_to_map(self.resource)
        return None

    @staticmethod
    def texts() -> Dict[str, str]:
        return {
            "edit": i18n.tr("Edit Raster"),
            "delete": i18n.tr("Delete Raster"),
            "add_many": i18n.tr("Add {} Rasters to Map"),
            "add_failed": i18n.tr("Some rasters could not be added"),
            "clear_many": i18n.tr("Clear Cache for {} Rasters"),
            "delete_many": i18n.tr("Delete {} Rasters"),
            "delete_title_many": i18n.tr("Delete Rasters"),
            "confirm_delete": i18n.tr("Are you sure you want to delete raster '{}'?"),
            "confirm_delete_many": i18n.tr(
                "Are you sure you want to delete {} rasters?\n{}"
            ),
            "deleted": i18n.tr("Raster '{}' deleted successfully."),
            "deleted_many": i18n.tr("{} rasters have been deleted successfully."),
            "delete_failed": i18n.tr("Some rasters could not be deleted"),
            "clear_all": i18n.tr("Clear Raster Cache Data"),
            "clear_all_loaded": i18n.tr(
                "Cannot clear raster cache while raster layers are loaded on the "
                "map. Please close your map first."
            ),
            "confirm_clear_all": i18n.tr(
                "This will clear all locally cached raster files ({}). "
                "Data will be re-downloaded next time you access rasters.\n\n"
                "Continue?"
            ),
            "all_cleared": i18n.tr(
                "All raster cache files have been cleared successfully."
            ),
            "load_failed": i18n.tr("Error loading rasters"),
            "empty": i18n.tr("No rasters found in this project"),
        }


class RasterRoot(ResourceRoot):
    """Root item for rasters in a project"""

    ITEM_CLASS = RasterItem
    UPLOAD_ALGORITHM = "kumoy:uploadraster"

    @staticmethod
    def fetch(project_id: str):
        return api.raster.get_rasters(project_id)

    def new_item(self, path: str, raster) -> RasterItem:
        return RasterItem(self, path, raster, self.project.role)

    def editor_actions(self, parent: QMenu) -> List[QAction]:
        upload_raster_action = QAction(i18n.tr("Upload Raster"), parent)
        upload_raster_action.triggered.connect(self.upload)
        return [upload_raster_action]
