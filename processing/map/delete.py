from typing import Any, Dict, Optional

from qgis.core import (
    QgsProcessingContext,
    QgsProcessingFeedback,
)

from ... import i18n
from ...kumoy import api, local_cache
from ..base import KumoyApiAlgorithm


class DeleteMapAlgorithm(KumoyApiAlgorithm):
    GROUP_ID = "map"
    MAP_ID = "MAP_ID"

    def name(self) -> str:
        return "deletemap"

    def displayName(self) -> str:
        return i18n.tr("Delete map")

    def shortHelpString(self) -> str:
        return i18n.tr(
            "Delete a Kumoy map and its local cache. "
            "This cannot be undone.\n\n"
            "The vectors and rasters used by the map are not deleted."
        )

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.add_id_parameter(self.MAP_ID, i18n.tr("Map ID"))
        self.add_output(self.MAP_ID, i18n.tr("Deleted map ID"))

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        map_id = self.parameter_as_id(parameters, self.MAP_ID, context)
        api.styledmap.delete_styled_map(map_id)
        feedback.pushInfo(i18n.tr("Deleted map: {}").format(map_id))

        if not local_cache.map.clear(map_id):
            feedback.pushWarning(
                i18n.tr("Could not clear the local cache of map: {}").format(map_id)
            )
        self.log_result(feedback, {"deleted": map_id})
        return {self.MAP_ID: map_id}
