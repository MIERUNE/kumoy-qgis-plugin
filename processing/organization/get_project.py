from typing import Any, Dict, Optional

from qgis.core import QgsProcessingContext, QgsProcessingFeedback

from ... import i18n
from ...kumoy import api
from ..base import KumoyApiAlgorithm, to_output


def _without_project(item: Dict[str, Any]) -> Dict[str, Any]:
    # Children of a project detail would otherwise repeat the whole parent
    return {k: v for k, v in item.items() if k != "project"}


class GetProjectAlgorithm(KumoyApiAlgorithm):
    GROUP_ID = "organization"
    PROJECT = "PROJECT"

    def name(self) -> str:
        return "getproject"

    def displayName(self) -> str:
        return i18n.tr("Get selected project details")

    def shortHelpString(self) -> str:
        return i18n.tr(
            "Get the details of the selected Kumoy project, including its "
            "vectors, rasters and maps.\n\n"
            "Output PROJECT is the project with 'vectors', 'rasters' and 'maps' "
            "lists."
        )

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.add_output(self.PROJECT, i18n.tr("Project"))

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        project_id = self.selected_project_id()

        project = to_output(api.project.get_project(project_id))
        project["vectors"] = [
            _without_project(v) for v in to_output(api.vector.get_vectors(project_id))
        ]
        project["rasters"] = to_output(api.raster.get_rasters(project_id))
        project["maps"] = [
            _without_project(m)
            for m in to_output(api.styledmap.get_styled_maps(project_id))
        ]

        return {self.PROJECT: project, **self.report(context, feedback, project)}
