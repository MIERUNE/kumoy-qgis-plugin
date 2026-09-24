from typing import Any, Dict, Optional

from qgis.core import (
    QgsProcessingContext,
    QgsProcessingFeedback,
)

from ... import i18n
from ...kumoy import api, local_cache
from ..base import KumoyApiAlgorithm


class DeleteRasterAlgorithm(KumoyApiAlgorithm):
    GROUP_ID = "raster"
    RASTER_ID = "RASTER_ID"

    def name(self) -> str:
        return "deleteraster"

    def displayName(self) -> str:
        return i18n.tr("Delete raster")

    def shortHelpString(self) -> str:
        return i18n.tr(
            "Delete a Kumoy raster in the selected project and its local cache. This cannot be undone.\n\n"
            "Layers of this raster already added to the map are not removed."
        )

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.add_id_parameter(self.RASTER_ID, i18n.tr("Raster ID"))
        self.add_output(self.RASTER_ID, i18n.tr("Deleted raster ID"))

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        raster_id = self.parameter_as_id(parameters, self.RASTER_ID, context)
        self.ensure_in_selected_project(api.raster.get_raster(raster_id).projectId)
        api.raster.delete_raster(raster_id)
        feedback.pushInfo(i18n.tr("Deleted raster: {}").format(raster_id))

        if not local_cache.raster.clear(raster_id):
            feedback.pushWarning(
                i18n.tr("Could not clear the local cache of raster: {}").format(
                    raster_id
                )
            )
        return {
            self.RASTER_ID: raster_id,
            **self.report(context, feedback, {"deleted": raster_id}),
        }
