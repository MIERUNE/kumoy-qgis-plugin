from typing import Any, Dict, Optional

from qgis.core import QgsProcessingContext, QgsProcessingFeedback

from ... import i18n
from ...kumoy import api
from ..base import KumoyApiAlgorithm, to_output, without_project


class ListRastersAlgorithm(KumoyApiAlgorithm):
    GROUP_ID = "raster"
    PROJECT_ID = "PROJECT_ID"
    RASTERS = "RASTERS"

    def name(self) -> str:
        return "listrasters"

    def displayName(self) -> str:
        return i18n.tr("List rasters in project")

    def shortHelpString(self) -> str:
        return i18n.tr("List the Kumoy rasters in a project.")

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.add_id_parameter(self.PROJECT_ID, i18n.tr("Project ID"))
        self.add_output(self.RASTERS, i18n.tr("Rasters"))

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        project_id = self.parameter_as_id(parameters, self.PROJECT_ID, context)
        rasters = [
            without_project(item)
            for item in to_output(api.raster.get_rasters(project_id))
        ]
        return {self.RASTERS: rasters, **self.report(context, feedback, rasters)}
