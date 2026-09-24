from typing import Any, Dict, Optional

from qgis.core import (
    Qgis,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingOutputRasterLayer,
)

from ... import i18n
from ...kumoy import api, constants, local_cache, raster_layer
from .base import KumoyApiAlgorithm, to_output


class GetRasterAlgorithm(KumoyApiAlgorithm):
    GROUP_ID = "raster"
    RASTER_ID = "RASTER_ID"
    RASTER = "RASTER"

    def name(self) -> str:
        return "getraster"

    def displayName(self) -> str:
        return i18n.tr("Get raster details")

    def shortHelpString(self) -> str:
        return i18n.tr(
            "Get the details of a Kumoy raster in the selected project.\n\n"
            "To create a raster, use 'Upload Raster Layer to Kumoy'."
        )

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.add_id_parameter(self.RASTER_ID, i18n.tr("Raster ID"))
        self.add_output(self.RASTER, i18n.tr("Raster"))

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        raster_id = self.parameter_as_id(parameters, self.RASTER_ID, context)
        detail = api.raster.get_raster(raster_id)
        self.ensure_in_selected_project(detail.projectId)

        raster = to_output(detail)
        return {self.RASTER: raster, **self.report(context, feedback, raster)}


class AddRasterToMapAlgorithm(KumoyApiAlgorithm):
    GROUP_ID = "raster"
    RASTER_ID = "RASTER_ID"
    OUTPUT = "OUTPUT"

    def name(self) -> str:
        return "addrastertomap"

    def displayName(self) -> str:
        return i18n.tr("Add raster to map")

    def shortHelpString(self) -> str:
        return i18n.tr(
            "Add a Kumoy raster in the selected project to the map as a layer. "
            "The raster is downloaded if it is not cached locally yet.\n\n"
            "From a script, use processing.runAndLoadResults() instead of "
            "processing.run() to add the layer to the project."
        )

    def flags(self) -> Qgis.ProcessingAlgorithmFlags:
        # The data provider shows a progress dialog while downloading, which
        # only works on the main thread
        return super().flags() | Qgis.ProcessingAlgorithmFlag.NoThreading

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


class UpdateRasterAlgorithm(KumoyApiAlgorithm):
    GROUP_ID = "raster"
    RASTER_ID = "RASTER_ID"
    NAME = "NAME"
    ATTRIBUTION = "ATTRIBUTION"
    RASTER = "RASTER"

    def name(self) -> str:
        return "updateraster"

    def displayName(self) -> str:
        return i18n.tr("Update raster")

    def shortHelpString(self) -> str:
        return i18n.tr(
            "Update the name or attribution of a Kumoy raster in the selected project.\n\n"
            "Leave a field empty to keep its current value."
        )

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.add_id_parameter(self.RASTER_ID, i18n.tr("Raster ID"))
        self.add_text_parameter(
            self.NAME, i18n.tr("New name"), constants.MAX_CHARACTERS_RASTER_NAME
        )
        self.add_text_parameter(
            self.ATTRIBUTION,
            i18n.tr("New attribution"),
            constants.MAX_CHARACTERS_RASTER_ATTRIBUTION,
        )
        self.add_output(self.RASTER, i18n.tr("Raster"))

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        raster_id = self.parameter_as_id(parameters, self.RASTER_ID, context)
        options = api.raster.UpdateRasterOptions(
            name=self.parameter_as_text(parameters, self.NAME, context),
            attribution=self.parameter_as_text(parameters, self.ATTRIBUTION, context),
        )
        if options.name is None and options.attribution is None:
            raise QgsProcessingException(i18n.tr("Nothing to update."))
        self.ensure_in_selected_project(api.raster.get_raster(raster_id).projectId)

        raster = to_output(api.raster.update_raster(raster_id, options))
        return {self.RASTER: raster, **self.report(context, feedback, raster)}


class DeleteRasterAlgorithm(KumoyApiAlgorithm):
    GROUP_ID = "raster"
    RASTER_ID = "RASTER_ID"

    def name(self) -> str:
        return "deleteraster"

    def displayName(self) -> str:
        return i18n.tr("Delete raster")

    def shortHelpString(self) -> str:
        return i18n.tr(
            "Delete a Kumoy raster in the selected project and its local cache. This cannot be undone.\n\n"
            "Layers of this raster already added to the map are not removed."
        )

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.add_id_parameter(self.RASTER_ID, i18n.tr("Raster ID"))
        self.add_output(self.RASTER_ID, i18n.tr("Deleted raster ID"))

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        raster_id = self.parameter_as_id(parameters, self.RASTER_ID, context)
        self.ensure_in_selected_project(api.raster.get_raster(raster_id).projectId)
        api.raster.delete_raster(raster_id)
        feedback.pushInfo(i18n.tr("Deleted raster: {}").format(raster_id))

        if not local_cache.raster.clear(raster_id):
            feedback.pushWarning(
                i18n.tr("Could not clear the local cache of raster: {}").format(
                    raster_id
                )
            )
        return {
            self.RASTER_ID: raster_id,
            **self.report(context, feedback, {"deleted": raster_id}),
        }
