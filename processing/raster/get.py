from typing import Any, Dict, Optional

from qgis.core import (
    QgsProcessingContext,
    QgsProcessingFeedback,
)

from ... import i18n
from ...kumoy import api
from ..base import KumoyApiAlgorithm, to_output


class GetRasterAlgorithm(KumoyApiAlgorithm):
    GROUP_ID = "raster"
    RASTER_ID = "RASTER_ID"
    RASTER = "RASTER"

    def name(self) -> str:
        return "getraster"

    def displayName(self) -> str:
        return i18n.tr("Get raster details")

    def shortHelpString(self) -> str:
        return i18n.tr(
            "Get the details of a Kumoy raster in the selected project.\n\n"
            "To create a raster, use 'Upload Raster Layer to Kumoy'."
        )

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.add_id_parameter(self.RASTER_ID, i18n.tr("Raster ID"))
        self.add_output(self.RASTER, i18n.tr("Raster"))

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        raster_id = self.parameter_as_id(parameters, self.RASTER_ID, context)
        detail = api.raster.get_raster(raster_id)
        self.ensure_in_selected_project(detail.projectId)

        raster = to_output(detail)
        return {self.RASTER: raster, **self.report(context, feedback, raster)}
