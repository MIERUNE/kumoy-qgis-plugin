from typing import Any, Dict, Optional

from qgis.core import (
    Qgis,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProcessingOutputVectorLayer,
)

from ... import i18n
from ...kumoy import api, vector_layer
from ..base import KumoyApiAlgorithm


class AddVectorToMapAlgorithm(KumoyApiAlgorithm):
    GROUP_ID = "vector"
    VECTOR_ID = "VECTOR_ID"
    OUTPUT = "OUTPUT"

    def name(self) -> str:
        return "addvectortomap"

    def displayName(self) -> str:
        return i18n.tr("Add vector to map")

    def shortHelpString(self) -> str:
        return i18n.tr(
            "Add a Kumoy vector in the selected project to the map as a layer.\n\n"
            "From a script, use processing.runAndLoadResults() instead of "
            "processing.run() to add the layer to the project."
        )

    def flags(self) -> Qgis.ProcessingAlgorithmFlags:
        # The data provider may show a progress dialog while syncing its local
        # cache, which only works on the main thread
        return super().flags() | Qgis.ProcessingAlgorithmFlag.NoThreading

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.add_id_parameter(self.VECTOR_ID, i18n.tr("Vector ID"))
        self.addOutput(QgsProcessingOutputVectorLayer(self.OUTPUT, i18n.tr("Layer")))

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        vector_id = self.parameter_as_id(parameters, self.VECTOR_ID, context)
        vector = api.vector.get_vector(vector_id)
        self.ensure_in_selected_project(vector.projectId)

        layer = vector_layer.create_vector_layer(vector)
        vector_layer.apply_pixel_based_style(layer)

        # Let Processing hand the layer to the project on completion instead of
        # touching QgsProject directly, so the algorithm respects the context
        context.temporaryLayerStore().addMapLayer(layer)
        context.addLayerToLoadOnCompletion(
            layer.id(),
            QgsProcessingContext.LayerDetails(
                vector.name, context.project(), self.OUTPUT
            ),
        )
        return {self.OUTPUT: layer.id()}
