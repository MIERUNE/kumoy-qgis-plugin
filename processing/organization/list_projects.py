from typing import Any, Dict, Optional

from qgis.core import QgsProcessingContext, QgsProcessingFeedback

from ... import i18n
from ...kumoy import api
from ..base import KumoyApiAlgorithm, to_output


class ListProjectsAlgorithm(KumoyApiAlgorithm):
    GROUP_ID = "organization"
    ORGANIZATION_ID = "ORGANIZATION_ID"
    PROJECTS = "PROJECTS"

    def name(self) -> str:
        return "listprojects"

    def displayName(self) -> str:
        return i18n.tr("List projects in organization")

    def shortHelpString(self) -> str:
        return i18n.tr(
            "List the Kumoy projects in an organization.\n\n"
            "Output PROJECTS is a list of projects with the number of vectors, "
            "rasters and maps they contain."
        )

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.add_id_parameter(self.ORGANIZATION_ID, i18n.tr("Organization ID"))
        self.add_output(self.PROJECTS, i18n.tr("Projects"))

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        organization_id = self.parameter_as_id(
            parameters, self.ORGANIZATION_ID, context
        )
        projects = to_output(api.project.get_projects_by_organization(organization_id))
        return {self.PROJECTS: projects, **self.report(context, feedback, projects)}
