from typing import Any, Dict, Optional

from qgis.core import QgsProcessingContext, QgsProcessingFeedback

from ... import i18n
from ...kumoy import api
from ..base import KumoyApiAlgorithm, to_output


class ListOrganizationsAlgorithm(KumoyApiAlgorithm):
    GROUP_ID = "organization"
    ORGANIZATIONS = "ORGANIZATIONS"

    def name(self) -> str:
        return "listorganizations"

    def displayName(self) -> str:
        return i18n.tr("List organizations")

    def shortHelpString(self) -> str:
        return i18n.tr(
            "List the Kumoy organizations you belong to.\n\n"
            "Output ORGANIZATIONS is a list of organizations. Organizations "
            "with scheduledDeletionAt set are awaiting deletion and unusable."
        )

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.add_output(self.ORGANIZATIONS, i18n.tr("Organizations"))

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        organizations = to_output(api.organization.get_organizations())
        return {
            self.ORGANIZATIONS: organizations,
            **self.report(context, feedback, organizations),
        }
