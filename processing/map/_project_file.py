from dataclasses import dataclass
from typing import Any, Dict, Optional

from qgis.core import (
    QgsProcessingException,
)

from ... import i18n
from ...kumoy import local_cache
from ...kumoy.sprite import SpriteData, generate_sprite

PROJECT_FILE_FILTER = "QGIS files (*.qgs *.qgz *.QGS *.QGZ)"


def without_qgisproject(styled_map: Dict[str, Any]) -> Dict[str, Any]:
    # The project XML can be megabytes; it is written to a file on request instead
    return {k: v for k, v in styled_map.items() if k != "qgisproject"}


@dataclass
class ProjectFile:
    qgisproject: str
    sprite: Optional[SpriteData]


def load_project_file(path: str) -> ProjectFile:
    project = local_cache.map.read_project_file(path)
    qgisproject = local_cache.map.serialize_detached_project(project)
    validate_size(qgisproject)
    return ProjectFile(qgisproject=qgisproject, sprite=generate_sprite(project))


def validate_size(qgisproject: str) -> None:
    size_error = local_cache.map.size_limit_error(qgisproject)
    if size_error:
        raise QgsProcessingException(size_error)


def project_file_help() -> str:
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
