from typing import Any, Dict, Optional

from qgis.core import QgsProcessingContext, QgsProcessingFeedback

from ... import i18n
from ...kumoy import api
from ..base import KumoyApiAlgorithm, to_output, without_project


class ListVectorsAlgorithm(KumoyApiAlgorithm):
    GROUP_ID = "vector"
    PROJECT_ID = "PROJECT_ID"
    VECTORS = "VECTORS"

    def name(self) -> str:
        return "listvectors"

    def displayName(self) -> str:
        return i18n.tr("List vectors in project")

    def shortHelpString(self) -> str:
        return i18n.tr("List the Kumoy vectors in a project.")

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.add_id_parameter(self.PROJECT_ID, i18n.tr("Project ID"))
        self.add_output(self.VECTORS, i18n.tr("Vectors"))

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        project_id = self.parameter_as_id(parameters, self.PROJECT_ID, context)
        vectors = [
            without_project(item)
            for item in to_output(api.vector.get_vectors(project_id))
        ]
        self.log_result(feedback, vectors)
        return {self.VECTORS: vectors}
