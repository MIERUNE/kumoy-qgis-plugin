import os
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, Optional

from qgis.core import (
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProject,
)

from ... import i18n
from ...kumoy import api, constants, local_cache
from ...kumoy.sprite import SpriteData, generate_sprite
from ...kumoy.sprite.uploader import upload_sprites
from .base import KumoyApiAlgorithm, to_output

_PROJECT_FILE_FILTER = "QGIS files (*.qgs *.qgz *.QGS *.QGZ)"


def _without_qgisproject(styled_map: Dict[str, Any]) -> Dict[str, Any]:
    # The project XML can be megabytes; it is written to a file on request instead
    return {k: v for k, v in styled_map.items() if k != "qgisproject"}


@dataclass
class _ProjectFile:
    qgisproject: str
    sprite: Optional[SpriteData]


def _load_project_file(path: str) -> _ProjectFile:
    project = local_cache.map.read_project_file(path)
    qgisproject = local_cache.map.serialize_detached_project(project)
    _validate_size(qgisproject)
    return _ProjectFile(qgisproject=qgisproject, sprite=generate_sprite(project))


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


def _validate_size(qgisproject: str) -> None:
    size_error = local_cache.map.size_limit_error(qgisproject)
    if size_error:
        raise QgsProcessingException(size_error)


def _project_file_help() -> str:
    return (
        i18n.tr(
            "The map extent saved in the project file becomes the default "
            "extent of the map.\n\n"
        )
        + i18n.tr(
            "Local layers in the project file are not converted to Kumoy layers. "
            "They are converted the next time the map is saved from QGIS."
        )
        + i18n.tr(
            "\n\nThe project file must be {:,} characters or less when saved as .qgs."
        ).format(local_cache.map.LENGTH_LIMIT)
    )


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
            + _project_file_help()
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
                fileFilter=_PROJECT_FILE_FILTER,
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
            _load_project_file(project_file)
            if project_file
            else _ProjectFile(qgisproject=_empty_project_xml(), sprite=None)
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

        result = _without_qgisproject(to_output(styled_map))
        return {self.MAP: result, **self.report(context, feedback, result)}


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

        result = _without_qgisproject(to_output(styled_map))
        results[self.MAP] = result
        results.update(self.report(context, feedback, result))
        return results


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
            + _project_file_help()
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
                fileFilter=_PROJECT_FILE_FILTER,
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
        loaded = _load_project_file(project_file) if project_file else None
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

        result = _without_qgisproject(to_output(styled_map))
        return {self.MAP: result, **self.report(context, feedback, result)}


class DeleteMapAlgorithm(KumoyApiAlgorithm):
    GROUP_ID = "map"
    MAP_ID = "MAP_ID"

    def name(self) -> str:
        return "deletemap"

    def displayName(self) -> str:
        return i18n.tr("Delete map")

    def shortHelpString(self) -> str:
        return i18n.tr(
            "Delete a Kumoy map in the selected project and its local cache. "
            "This cannot be undone.\n\n"
            "The vectors and rasters used by the map are not deleted."
        )

    def initAlgorithm(self, _: Optional[Dict[str, Any]] = None) -> None:
        self.add_id_parameter(self.MAP_ID, i18n.tr("Map ID"))
        self.add_output(self.MAP_ID, i18n.tr("Deleted map ID"))

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        map_id = self.parameter_as_id(parameters, self.MAP_ID, context)
        self.ensure_in_selected_project(api.styledmap.get_styled_map(map_id).projectId)
        api.styledmap.delete_styled_map(map_id)
        feedback.pushInfo(i18n.tr("Deleted map: {}").format(map_id))

        if not local_cache.map.clear(map_id):
            feedback.pushWarning(
                i18n.tr("Could not clear the local cache of map: {}").format(map_id)
            )
        return {
            self.MAP_ID: map_id,
            **self.report(context, feedback, {"deleted": map_id}),
        }
