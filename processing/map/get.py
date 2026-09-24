from typing import Any, Dict, Optional

from qgis.core import (
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProcessingParameterFileDestination,
)

from ... import i18n
from ...kumoy import api
from ..base import KumoyApiAlgorithm, to_output
from ._project_file import (
    without_qgisproject,
)


class GetMapAlgorithm(KumoyApiAlgorithm):
    GROUP_ID = "map"
    MAP_ID = "MAP_ID"
    PROJECT_FILE = "PROJECT_FILE"
    MAP = "MAP"

    def name(self) -> str:
        return "getmap"

    def displayName(self) -> str:
        return i18n.tr("Get map details")

    def shortHelpString(self) -> str:
        return i18n.tr(
            "Get the details of a Kumoy map in the selected project.\n\n"
            "Optionally, save the map's QGIS project (.qgs) to a file."
        )

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.add_id_parameter(self.MAP_ID, i18n.tr("Map ID"))
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.PROJECT_FILE,
                i18n.tr("Save QGIS project to"),
                fileFilter="QGIS files (*.qgs *.QGS)",
                optional=True,
                createByDefault=False,
            )
        )
        self.add_output(self.MAP, i18n.tr("Map"))

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        map_id = self.parameter_as_id(parameters, self.MAP_ID, context)
        styled_map = api.styledmap.get_styled_map(map_id)
        self.ensure_in_selected_project(styled_map.projectId)

        results: Dict[str, Any] = {}
        project_file = self.parameterAsFileOutput(
            parameters, self.PROJECT_FILE, context
        )
        if project_file:
            with open(project_file, "w", encoding="utf-8") as f:
                f.write(styled_map.qgisproject)
            feedback.pushInfo(i18n.tr("Saved QGIS project to {}").format(project_file))
            results[self.PROJECT_FILE] = project_file

        result = without_qgisproject(to_output(styled_map))
        results[self.MAP] = result
        results.update(self.report(context, feedback, result))
        return results
