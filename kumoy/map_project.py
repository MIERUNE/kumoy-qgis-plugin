"""Serialize QGIS projects for Kumoy maps (no UI, no network).

A Kumoy map is opened in QGIS as a project stored in the "kumoy" project
storage under the URI ``kumoy:<map id>`` (see ui/project_storage.py).
"""

import os
import re
import tempfile
from typing import List, Optional

from qgis.core import Qgis, QgsProject, QgsVectorLayer

from .. import i18n
from .api.styledmap import MAX_QGISPROJECT_LENGTH
from .constants import DATA_PROVIDER_KEY, RASTER_DATA_PROVIDER_KEY
from .sprite import pin_fixed_aspect_ratios

STORAGE_TYPE = "kumoy"
_URI_PREFIX = f"{STORAGE_TYPE}:"


def map_uri(map_id: str) -> str:
    return f"{_URI_PREFIX}{map_id}"


def map_id_from_uri(uri: str) -> Optional[str]:
    """The map ID of a ``kumoy:<map id>`` URI, or None for any other path."""
    if not uri or not uri.startswith(_URI_PREFIX):
        return None
    return uri[len(_URI_PREFIX) :] or None


def refresh_kumoy_layer_extents(project: QgsProject) -> None:
    """Re-read the extent of every Kumoy vector layer from its provider.

    QgsVectorLayer caches the provider extent for the layer's lifetime, and
    write() omits <extent> entirely when it is null. A Kumoy layer returns null
    while the server has no extent yet (empty/just-uploaded vector, failed
    metadata fetch), so a layer unlucky in when it was first asked would be
    saved without an extent forever after.

    Vector layers only: other providers don't have this bug and rescanning them
    can be expensive; QgsRasterLayer has no updateExtents().
    """
    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue
        provider = layer.dataProvider()
        if provider is None or provider.name() != DATA_PROVIDER_KEY:
            continue
        # Preferred: recomputes from the provider and folds in uncommitted edits
        layer.updateExtents()
        if not layer.extent().isNull():  # also forces the recompute now
            continue
        # updateExtents() is a no-op while featureCount() is 0, so write the
        # server extent directly for layers that cannot produce features
        provider_extent = provider.extent()
        if not provider_extent.isNull():
            layer.setExtent(provider_extent)


def prepare(project: QgsProject) -> None:
    """Adjust the project so that the web map renders it like QGIS does."""
    pin_fixed_aspect_ratios(project)
    refresh_kumoy_layer_extents(project)


def write_xml(project: QgsProject) -> str:
    """Write the project as .qgs XML via a temporary file and return it.

    Paths are always written absolute: relative ones would be relative to the
    temporary file, which means nothing to whoever opens the map. (QGIS only
    falls back to absolute when the paths share no prefix with the temporary
    directory, which on Windows they usually do: both are under C:\\Users.)

    QgsProject.write() points the project at the temporary file and marks it
    clean: callers serializing the open project must restore both.
    """
    previous = project.filePathStorage()
    project.setFilePathStorage(Qgis.FilePathType.Absolute)
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "project.qgs")  # .qgs: plain XML, not zipped
            if not project.write(path):
                raise RuntimeError(
                    i18n.tr("Failed to serialize the project: {}").format(
                        project.error()
                    )
                )
            with open(path, encoding="utf-8") as f:
                return f.read()
    finally:
        project.setFilePathStorage(previous)


def serialize_detached(project: QgsProject) -> str:
    """Serialize a project that is not the one open in QGIS."""
    prepare(project)
    return write_xml(project)


def read_project_file(path: str) -> QgsProject:
    """Read a .qgs / .qgz into a standalone project, leaving the open one untouched."""
    project = QgsProject()
    if not project.read(path):
        raise RuntimeError(
            i18n.tr("Failed to read the QGIS project file: {}").format(project.error())
        )
    return project


def empty_project_xml() -> str:
    # A standalone QgsProject leaves the project open in QGIS untouched
    return write_xml(QgsProject())


def size_error(qgisproject: str) -> Optional[str]:
    """A message when the XML is over the server's limit, else None."""
    if len(qgisproject) <= MAX_QGISPROJECT_LENGTH:
        return None
    return i18n.tr(
        "The project is too large to save as a Kumoy map: {:,} characters, "
        "the limit is {:,}. Remove layers or embedded images (for example "
        "embedded SVG symbols) and try again."
    ).format(len(qgisproject), MAX_QGISPROJECT_LENGTH)


_PROJECT_ID = re.compile(r"(?:^|;)project_id=([^;]*)")


def foreign_kumoy_layers(project: QgsProject, project_id: str) -> List[str]:
    """Names of Kumoy layers that belong to another Kumoy project.

    The web map resolves layers within the map's project, so they would be
    missing there.
    """
    names = []
    for layer in project.mapLayers().values():
        if layer.providerType() not in (DATA_PROVIDER_KEY, RASTER_DATA_PROVIDER_KEY):
            continue
        match = _PROJECT_ID.search(layer.source())
        if match and match.group(1) != project_id:
            names.append(layer.name())
    return names
