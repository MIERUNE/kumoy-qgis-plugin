from typing import Any, Dict, Optional

from qgis.core import (
    QgsProcessingContext,
    QgsProcessingFeedback,
)

from ... import i18n
from ...kumoy import api
from ..base import KumoyApiAlgorithm, to_output


class GetVectorAlgorithm(KumoyApiAlgorithm):
    GROUP_ID = "vector"
    VECTOR_ID = "VECTOR_ID"
    VECTOR = "VECTOR"

    def name(self) -> str:
        return "getvector"

    def displayName(self) -> str:
        return i18n.tr("Get vector details")

    def shortHelpString(self) -> str:
        return i18n.tr(
            "Get the details of a Kumoy vector in the selected project: geometry type, extent, feature "
            "count and columns.\n\n"
            "To create a vector, use 'Upload Vector Layer to Kumoy'."
        )

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.add_id_parameter(self.VECTOR_ID, i18n.tr("Vector ID"))
        self.add_output(self.VECTOR, i18n.tr("Vector"))

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        vector_id = self.parameter_as_id(parameters, self.VECTOR_ID, context)
        detail = api.vector.get_vector(vector_id)
        self.ensure_in_selected_project(detail.projectId)

        vector = to_output(detail)
        return {self.VECTOR: vector, **self.report(context, feedback, vector)}
