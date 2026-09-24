import os
import tempfile
from typing import Any, Dict, Optional

from qgis.core import (
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFile,
    QgsProject,
)

from ... import i18n
from ...kumoy import api, constants
from ...kumoy.sprite.uploader import upload_sprites
from ..base import KumoyApiAlgorithm, to_output
from ._project_file import (
    PROJECT_FILE_FILTER,
    ProjectFile,
    load_project_file,
    project_file_help,
    without_qgisproject,
)


def _empty_project_xml() -> str:
    # A standalone QgsProject leaves the project open in QGIS untouched
    fd, tmp_path = tempfile.mkstemp(suffix=".qgs")
    os.close(fd)
    try:
        if not QgsProject().write(tmp_path):
            raise QgsProcessingException(i18n.tr("Failed to create an empty project."))
        with open(tmp_path, encoding="utf-8") as f:
            return f.read()
    finally:
        os.remove(tmp_path)


class CreateMapAlgorithm(KumoyApiAlgorithm):
    GROUP_ID = "map"
    NAME = "NAME"
    DESCRIPTION = "DESCRIPTION"
    ATTRIBUTION = "ATTRIBUTION"
    IS_PUBLIC = "IS_PUBLIC"
    PROJECT_FILE = "PROJECT_FILE"
    MAP = "MAP"

    def name(self) -> str:
        return "createmap"

    def displayName(self) -> str:
        return i18n.tr("Create map")

    def shortHelpString(self) -> str:
        return (
            i18n.tr(
                "Create a Kumoy map in the selected project from a QGIS project file "
                "(.qgs / .qgz). Without a file, an empty map is created.\n\n"
            )
            + project_file_help()
        )

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.add_text_parameter(
            self.NAME,
            i18n.tr("Name"),
            constants.MAX_CHARACTERS_STYLEDMAP_NAME,
            optional=False,
        )
        self.add_text_parameter(
            self.DESCRIPTION,
            i18n.tr("Description"),
            constants.MAX_CHARACTERS_STYLEDMAP_DESCRIPTION,
        )
        self.add_text_parameter(
            self.ATTRIBUTION,
            i18n.tr("Attribution"),
            constants.MAX_CHARACTERS_STYLEDMAP_ATTRIBUTION,
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.IS_PUBLIC, i18n.tr("Public"), defaultValue=False
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.PROJECT_FILE,
                i18n.tr("QGIS project file"),
                fileFilter=PROJECT_FILE_FILTER,
                optional=True,
            )
        )
        self.add_output(self.MAP, i18n.tr("Map"))

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        project_id = self.selected_project_id()
        name = self.parameter_as_text(parameters, self.NAME, context)

        project_file = self.parameterAsFile(parameters, self.PROJECT_FILE, context)
        loaded = (
            load_project_file(project_file)
            if project_file
            else ProjectFile(qgisproject=_empty_project_xml(), sprite=None)
        )

        styled_map = api.styledmap.add_styled_map(
            project_id,
            api.styledmap.AddStyledMapOptions(
                name=name,
                qgisproject=loaded.qgisproject,
                description=self.parameter_as_text(
                    parameters, self.DESCRIPTION, context
                ),
                attribution=self.parameter_as_text(
                    parameters, self.ATTRIBUTION, context
                ),
                isPublic=self.parameterAsBoolean(parameters, self.IS_PUBLIC, context),
            ),
        )
        # Sprites are stored per map, so they can only be uploaded once it exists
        if loaded.sprite is not None:
            upload_sprites(styled_map.id, loaded.sprite)
            styled_map = api.styledmap.update_styled_map(
                styled_map.id,
                api.styledmap.UpdateStyledMapOptions(
                    assetsHash=loaded.sprite.assets_hash
                ),
            )

        result = without_qgisproject(to_output(styled_map))
        return {self.MAP: result, **self.report(context, feedback, result)}
