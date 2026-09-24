from typing import Any, Dict, Optional

from qgis.core import (
    QgsProcessingContext,
    QgsProcessingFeedback,
)

from ... import i18n
from ...kumoy import api, local_cache
from ..base import KumoyApiAlgorithm


class DeleteVectorAlgorithm(KumoyApiAlgorithm):
    GROUP_ID = "vector"
    VECTOR_ID = "VECTOR_ID"

    def name(self) -> str:
        return "deletevector"

    def displayName(self) -> str:
        return i18n.tr("Delete vector")

    def shortHelpString(self) -> str:
        return i18n.tr(
            "Delete a Kumoy vector in the selected project and its local cache. This cannot be undone.\n\n"
            "Layers of this vector already added to the map are not removed."
        )

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.add_id_parameter(self.VECTOR_ID, i18n.tr("Vector ID"))
        self.add_output(self.VECTOR_ID, i18n.tr("Deleted vector ID"))

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        vector_id = self.parameter_as_id(parameters, self.VECTOR_ID, context)
        self.ensure_in_selected_project(api.vector.get_vector(vector_id).projectId)
        api.vector.delete_vector(vector_id)
        feedback.pushInfo(i18n.tr("Deleted vector: {}").format(vector_id))

        if not local_cache.vector.clear(vector_id):
            feedback.pushWarning(
                i18n.tr("Could not clear the local cache of vector: {}").format(
                    vector_id
                )
            )
        return {
            self.VECTOR_ID: vector_id,
            **self.report(context, feedback, {"deleted": vector_id}),
        }
