from dataclasses import dataclass
from typing import Any, Dict, Optional

from qgis.core import Qgis, QgsProcessingException, QgsProject
from qgis.gui import QgsMapCanvas
from qgis.PyQt import sip

from ... import i18n
from ...kumoy import local_cache
from ...kumoy.sprite import SpriteData, generate_sprite

PROJECT_FILE_FILTER = "QGIS files (*.qgs *.qgz *.QGS *.QGZ)"

# Kumoy takes the initial view of a map from the <mapcanvas> of this name
_MAP_CANVAS_NAME = "theMapCanvas"


def without_qgisproject(styled_map: Dict[str, Any]) -> Dict[str, Any]:
    # The project XML can be megabytes; it is written to a file on request instead
    return {k: v for k, v in styled_map.items() if k != "qgisproject"}


@dataclass
class ProjectFile:
    qgisproject: str
    sprite: Optional[SpriteData]


def load_project_file(path: str) -> ProjectFile:
    project = local_cache.map.read_project_file(path)
    qgisproject = _serialize_with_map_canvas(project, path)
    validate_size(qgisproject)
    return ProjectFile(qgisproject=qgisproject, sprite=generate_sprite(project))


def _serialize_with_map_canvas(project: QgsProject, path: str) -> str:
    """Serialize the project with the map view saved in the file at path.

    Only QgsMapCanvas reads and writes <mapcanvas>, and the canvas of the QGIS
    window belongs to the open project, so a standalone one stands in here.
    """
    canvas = QgsMapCanvas()
    try:
        canvas.setObjectName(_MAP_CANVAS_NAME)
        # The canvas is also wired to QgsProject.instance(), so it must not
        # outlive this synchronous block: saving the open project meanwhile
        # would add a second <mapcanvas>. Reading the file again without
        # resolving layers keeps provider dialogs (and their event loop) out.
        view = QgsProject()
        view.crsChanged.connect(lambda: canvas.setDestinationCrs(view.crs()))
        # readProject() takes the project from sender() when the file has no
        # <mapcanvas>, so it must be called through the signal
        view.readProject.connect(canvas.readProject)
        view.read(path, Qgis.ProjectReadFlag.DontResolveLayers)

        canvas.setProject(project)
        if canvas.extent().isEmpty():
            canvas.zoomToProjectExtent()
        # An empty project has no extent; writing it would put ±1.8e308 in the XML
        if not canvas.extent().isEmpty():
            project.writeProject.connect(canvas.writeProject)
        return local_cache.map.serialize_detached_project(project)
    finally:
        sip.delete(canvas)


def validate_size(qgisproject: str) -> None:
    size_error = local_cache.map.size_limit_error(qgisproject)
    if size_error:
        raise QgsProcessingException(size_error)


def project_file_help() -> str:
    return (
        i18n.tr(
            "The map extent saved in the project file becomes the default "
            "extent of the map. A project built by a script has no map canvas; "
            "set its default view extent with "
            "project.viewSettings().setDefaultViewExtent(), otherwise the full "
            "extent of the layers is used.\n\n"
        )
        + i18n.tr(
            "Local layers in the project file are not converted to Kumoy layers. "
            "They are converted the next time the map is saved from QGIS."
        )
        + i18n.tr(
            "\n\nKumoy layers in the project file are loaded as in QGIS, so their "
            "data is downloaded to the local cache if it is not cached yet."
        )
        + i18n.tr(
            "\n\nThe Kumoy layers in the project file must belong to the same "
            "Kumoy project as the map. A map cannot mix layers from different "
            "projects."
        )
        + i18n.tr(
            "\n\nThe project file must be {:,} characters or less when saved as .qgs."
        ).format(local_cache.map.LENGTH_LIMIT)
    )
