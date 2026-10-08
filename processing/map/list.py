from typing import Any, Dict, Optional

from qgis.core import QgsProcessingContext, QgsProcessingFeedback

from ... import i18n
from ...kumoy import api
from ..base import KumoyApiAlgorithm, to_output, without_project


class ListMapsAlgorithm(KumoyApiAlgorithm):
    GROUP_ID = "map"
    PROJECT_ID = "PROJECT_ID"
    MAPS = "MAPS"

    def name(self) -> str:
        return "listmaps"

    def displayName(self) -> str:
        return i18n.tr("List maps in project")

    def shortHelpString(self) -> str:
        return i18n.tr("List the Kumoy maps in a project.")

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.add_id_parameter(self.PROJECT_ID, i18n.tr("Project ID"))
        self.add_output(self.MAPS, i18n.tr("Maps"))

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        project_id = self.parameter_as_id(parameters, self.PROJECT_ID, context)
        maps = [
            without_project(item)
            for item in to_output(api.styledmap.get_styled_maps(project_id))
        ]
        self.log_result(feedback, maps)
        return {self.MAPS: maps}
