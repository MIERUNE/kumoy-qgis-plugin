from typing import Any, Dict, Optional

from qgis.core import (
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
)

from ... import i18n
from ...kumoy import api, constants
from ..base import KumoyApiAlgorithm, to_output


class UpdateRasterAlgorithm(KumoyApiAlgorithm):
    GROUP_ID = "raster"
    RASTER_ID = "RASTER_ID"
    NAME = "NAME"
    ATTRIBUTION = "ATTRIBUTION"
    RASTER = "RASTER"

    def name(self) -> str:
        return "updateraster"

    def displayName(self) -> str:
        return i18n.tr("Update raster")

    def shortHelpString(self) -> str:
        return i18n.tr(
            "Update the name or attribution of a Kumoy raster in the selected project.\n\n"
            "Leave a field empty to keep its current value."
        )

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.add_id_parameter(self.RASTER_ID, i18n.tr("Raster ID"))
        self.add_text_parameter(
            self.NAME, i18n.tr("New name"), constants.MAX_CHARACTERS_RASTER_NAME
        )
        self.add_text_parameter(
            self.ATTRIBUTION,
            i18n.tr("New attribution"),
            constants.MAX_CHARACTERS_RASTER_ATTRIBUTION,
        )
        self.add_output(self.RASTER, i18n.tr("Raster"))

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        raster_id = self.parameter_as_id(parameters, self.RASTER_ID, context)
        options = api.raster.UpdateRasterOptions(
            name=self.parameter_as_text(parameters, self.NAME, context),
            attribution=self.parameter_as_text(parameters, self.ATTRIBUTION, context),
        )
        if options.name is None and options.attribution is None:
            raise QgsProcessingException(i18n.tr("Nothing to update."))
        self.ensure_in_selected_project(api.raster.get_raster(raster_id).projectId)

        raster = to_output(api.raster.update_raster(raster_id, options))
        return {self.RASTER: raster, **self.report(context, feedback, raster)}
