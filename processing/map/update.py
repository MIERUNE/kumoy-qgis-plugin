from typing import Any, Dict, Optional

from qgis.core import (
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFile,
)

from ... import i18n
from ...kumoy import api, constants
from ...kumoy.sprite.uploader import upload_sprites
from ..base import KumoyApiAlgorithm, to_output
from ._project_file import (
    PROJECT_FILE_FILTER,
    load_project_file,
    project_file_help,
    without_qgisproject,
)


class UpdateMapAlgorithm(KumoyApiAlgorithm):
    GROUP_ID = "map"
    MAP_ID = "MAP_ID"
    NAME = "NAME"
    DESCRIPTION = "DESCRIPTION"
    ATTRIBUTION = "ATTRIBUTION"
    IS_PUBLIC = "IS_PUBLIC"
    PROJECT_FILE = "PROJECT_FILE"
    MAP = "MAP"

    # Index of IS_PUBLIC options
    KEEP, PUBLIC, PRIVATE = 0, 1, 2

    def name(self) -> str:
        return "updatemap"

    def displayName(self) -> str:
        return i18n.tr("Update map")

    def shortHelpString(self) -> str:
        return (
            i18n.tr(
                "Update the properties of a Kumoy map in the selected project, or "
                "replace its QGIS "
                "project with a file (.qgs / .qgz).\n\n"
                "Leave a field empty to keep its current value.\n\n"
            )
            + project_file_help()
        )

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.add_id_parameter(self.MAP_ID, i18n.tr("Map ID"))
        self.add_text_parameter(
            self.NAME, i18n.tr("New name"), constants.MAX_CHARACTERS_STYLEDMAP_NAME
        )
        self.add_text_parameter(
            self.DESCRIPTION,
            i18n.tr("New description"),
            constants.MAX_CHARACTERS_STYLEDMAP_DESCRIPTION,
        )
        self.add_text_parameter(
            self.ATTRIBUTION,
            i18n.tr("New attribution"),
            constants.MAX_CHARACTERS_STYLEDMAP_ATTRIBUTION,
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.IS_PUBLIC,
                i18n.tr("Visibility"),
                options=[
                    i18n.tr("Keep current"),
                    i18n.tr("Public"),
                    i18n.tr("Private"),
                ],
                defaultValue=self.KEEP,
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.PROJECT_FILE,
                i18n.tr("Replace with QGIS project file"),
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
        map_id = self.parameter_as_id(parameters, self.MAP_ID, context)
        visibility = self.parameterAsEnum(parameters, self.IS_PUBLIC, context)

        options = api.styledmap.UpdateStyledMapOptions(
            name=self.parameter_as_text(parameters, self.NAME, context),
            description=self.parameter_as_text(parameters, self.DESCRIPTION, context),
            attribution=self.parameter_as_text(parameters, self.ATTRIBUTION, context),
            isPublic=None if visibility == self.KEEP else visibility == self.PUBLIC,
        )

        project_file = self.parameterAsFile(parameters, self.PROJECT_FILE, context)
        loaded = load_project_file(project_file) if project_file else None
        if loaded is not None:
            options.qgisproject = loaded.qgisproject

        if all(
            value is None
            for value in (
                options.name,
                options.description,
                options.attribution,
                options.isPublic,
                options.qgisproject,
            )
        ):
            raise QgsProcessingException(i18n.tr("Nothing to update."))
        current = api.styledmap.get_styled_map(map_id)
        self.ensure_in_selected_project(current.projectId)

        if loaded is not None:
            new_assets_hash = loaded.sprite.assets_hash if loaded.sprite else None
            # The old sprites no longer match the replaced project's symbols
            if new_assets_hash != current.assetsHash:
                if loaded.sprite is not None:
                    upload_sprites(map_id, loaded.sprite)
                # None clears the hash when the project has no point symbols
                options.assetsHash = new_assets_hash

        styled_map = api.styledmap.update_styled_map(map_id, options)

        result = without_qgisproject(to_output(styled_map))
        return {self.MAP: result, **self.report(context, feedback, result)}
