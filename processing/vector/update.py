from typing import Any, Dict, Optional

from qgis.core import (
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
)

from ... import i18n
from ...kumoy import api, constants
from ..base import KumoyApiAlgorithm, to_output


class UpdateVectorAlgorithm(KumoyApiAlgorithm):
    GROUP_ID = "vector"
    VECTOR_ID = "VECTOR_ID"
    NAME = "NAME"
    ATTRIBUTION = "ATTRIBUTION"
    VECTOR = "VECTOR"

    def name(self) -> str:
        return "updatevector"

    def displayName(self) -> str:
        return i18n.tr("Update vector")

    def shortHelpString(self) -> str:
        return i18n.tr(
            "Update the name or attribution of a Kumoy vector in the selected project.\n\n"
            "Leave a field empty to keep its current value."
        )

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.add_id_parameter(self.VECTOR_ID, i18n.tr("Vector ID"))
        self.add_text_parameter(
            self.NAME, i18n.tr("New name"), constants.MAX_CHARACTERS_VECTOR_NAME
        )
        self.add_text_parameter(
            self.ATTRIBUTION,
            i18n.tr("New attribution"),
            constants.MAX_CHARACTERS_VECTOR_ATTRIBUTION,
        )
        self.add_output(self.VECTOR, i18n.tr("Vector"))

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        vector_id = self.parameter_as_id(parameters, self.VECTOR_ID, context)
        options = api.vector.UpdateVectorOptions(
            name=self.parameter_as_text(parameters, self.NAME, context),
            attribution=self.parameter_as_text(parameters, self.ATTRIBUTION, context),
        )
        if options.name is None and options.attribution is None:
            raise QgsProcessingException(i18n.tr("Nothing to update."))
        self.ensure_in_selected_project(api.vector.get_vector(vector_id).projectId)

        vector = to_output(api.vector.update_vector(vector_id, options))
        return {self.VECTOR: vector, **self.report(context, feedback, vector)}
