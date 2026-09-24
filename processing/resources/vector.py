from typing import Any, Dict, Optional

from qgis.core import (
    Qgis,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingOutputVectorLayer,
)

from ... import i18n
from ...kumoy import api, constants, local_cache, vector_layer
from .base import KumoyApiAlgorithm, to_output


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
