from typing import Any, Dict, Optional

from qgis.core import (
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProcessingOutputRasterLayer,
)

from ... import i18n
from ...kumoy import api, raster_layer
from ..base import KumoyApiAlgorithm


class AddRasterToMapAlgorithm(KumoyApiAlgorithm):
    GROUP_ID = "raster"
    RASTER_ID = "RASTER_ID"
    OUTPUT = "OUTPUT"
    # The data provider shows a progress dialog while syncing its local cache
    REQUIRES_MAIN_THREAD = True

    def name(self) -> str:
        return "addrastertomap"

    def displayName(self) -> str:
        return i18n.tr("Add raster to map")

    def shortHelpString(self) -> str:
        return (
            i18n.tr(
                "Add a Kumoy raster in the selected project to the map as a layer. "
                "The raster is downloaded if it is not cached locally yet.\n\n"
                "From a script, use processing.runAndLoadResults() instead of "
                "processing.run() to add the layer to the project."
            )
            + self.main_thread_help()
        )

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.add_id_parameter(self.RASTER_ID, i18n.tr("Raster ID"))
        self.addOutput(QgsProcessingOutputRasterLayer(self.OUTPUT, i18n.tr("Layer")))

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        raster_id = self.parameter_as_id(parameters, self.RASTER_ID, context)
        raster = api.raster.get_raster(raster_id)
        self.ensure_in_selected_project(raster.projectId)

        layer = raster_layer.create_raster_layer(raster)

        # Let Processing hand the layer to the project on completion instead of
        # touching QgsProject directly, so the algorithm respects the context
        context.temporaryLayerStore().addMapLayer(layer)
        context.addLayerToLoadOnCompletion(
            layer.id(),
            QgsProcessingContext.LayerDetails(
                raster.name, context.project(), self.OUTPUT
            ),
        )
        return {self.OUTPUT: layer.id()}
