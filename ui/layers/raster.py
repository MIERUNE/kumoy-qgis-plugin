"""Kumoy raster layers in the open project: add, show downloads, reload after.

A Kumoy raster layer whose COG is not cached yet starts as an empty
placeholder (see kumoy/provider/raster_dataprovider.py) while the download
runs in the background. register() hooks the downloads so those layers show
the progress in the Layers panel and come alive by themselves once the file
is there.
"""

from typing import Dict, List, Set

from qgis.core import Qgis, QgsApplication, QgsMapLayer, QgsProject
from qgis.PyQt.QtCore import QTimer
from qgis.utils import iface

from ... import i18n
from ...kumoy import constants, download, raster_layer, session
from ...kumoy.api.error import NotFoundError, format_api_error
from ...kumoy.api.models import Raster
from ...kumoy.provider.raster_dataprovider import parse_uri
from ..error_handler import handle_api_error
from ..utils import reload_layer
from . import download_indicator

# Per raster being downloaded: {"progress": 0-100} or, after a failure,
# {"error": message, "name": raster name}
_state: Dict[str, Dict[str, object]] = {}
# Layers add_raster_to_map() added before their download finished: removed
# again when the user cancels the download
_added_while_downloading: Dict[str, Set[str]] = {}


def register() -> None:
    download.fetcher.ready.connect(_on_ready)
    download.fetcher.failed.connect(_on_failed)
    # The fetcher has no "started" signal (it is shared across plugin
    # reloads); its tasks carry the raster ID instead
    QgsApplication.taskManager().taskAdded.connect(_on_task_added)
    session.add_listener(_on_session_changed)
    project = QgsProject.instance()
    project.layersAdded.connect(_on_layers_added)
    project.layerTreeRoot().addedChildren.connect(_on_layers_added)


def unregister() -> None:
    session.remove_listener(_on_session_changed)
    project = QgsProject.instance()
    for signal, slot in (
        (download.fetcher.ready, _on_ready),
        (download.fetcher.failed, _on_failed),
        (QgsApplication.taskManager().taskAdded, _on_task_added),
        (project.layersAdded, _on_layers_added),
        (project.layerTreeRoot().addedChildren, _on_layers_added),
    ):
        try:
            signal.disconnect(slot)
        except TypeError:
            pass  # register() was not called
    for raster_id in list(_state):
        del _state[raster_id]
        _update_indicators(raster_id)
    _added_while_downloading.clear()


def add_raster_to_map(raster: Raster) -> None:
    """Add `raster` to the project now; it fills in once its COG is cached.

    Until then the layer is an empty placeholder whose indicator shows the
    download, which can be canceled in the task manager (the layer is then
    removed again). On reload it gets the default style of the real bands.
    """
    try:
        layer = raster_layer.create_raster_layer(raster)
    except Exception as e:
        handle_api_error(e)
        return
    QgsProject.instance().addMapLayer(layer)
    if layer.dataProvider() is not None and layer.dataProvider().xSize() == 0:
        _added_while_downloading.setdefault(raster.id, set()).add(layer.id())


def _placeholders():
    """(layer, raster_id, raster_name) of the project's not-yet-loaded rasters."""
    for layer in QgsProject.instance().mapLayers().values():
        if layer.providerType() != constants.RASTER_DATA_PROVIDER_KEY:
            continue
        provider = layer.dataProvider()
        # xSize() == 0: still the placeholder. A layer that already reads the
        # COG must not be reloaded: that would undo edits made since it opened
        if provider is None or provider.xSize() != 0:
            continue
        try:
            _, raster_id, raster_name = parse_uri(layer.source())
        except ValueError:
            continue
        yield layer, raster_id, raster_name


def _placeholders_of(raster_id: str) -> List[QgsMapLayer]:
    return [layer for layer, rid, _ in _placeholders() if rid == raster_id]


def _on_session_changed() -> None:
    # A project opened before login (e.g. at QGIS startup, before the session
    # is loaded) could not download its rasters; retry now
    if session.is_logged_in():
        for _, raster_id, raster_name in _placeholders():
            download.fetch_raster(raster_id, raster_name)


def reload_layers(raster_id: str) -> None:
    """Reload the project's placeholder layers of `raster_id` from the cache."""
    for layer in _placeholders_of(raster_id):
        reload_layer(layer, constants.RASTER_DATA_PROVIDER_KEY)


# --- Download progress ------------------------------------------------------


def _on_task_added(task_id: int) -> None:
    task = QgsApplication.taskManager().task(task_id)
    raster_id = task.property(download.TASK_RASTER_ID_PROPERTY) if task else None
    if not raster_id:
        return
    _state[raster_id] = {"progress": 0.0}
    task.progressChanged.connect(lambda p, r=raster_id: _on_progress(r, p))
    # Deferred: on a failure the fetcher's failed signal, which records the
    # error, may come after taskTerminated
    task.taskTerminated.connect(
        lambda r=raster_id: QTimer.singleShot(0, lambda: _on_terminated(r))
    )
    _update_indicators(raster_id)


def _on_progress(raster_id: str, progress: float) -> None:
    state = _state.get(raster_id)
    if state is not None and "error" not in state:
        state["progress"] = progress
        _update_indicators(raster_id)


def _on_ready(raster_id: str) -> None:
    reload_layers(raster_id)
    _state.pop(raster_id, None)
    _added_while_downloading.pop(raster_id, None)
    _update_indicators(raster_id)


def _on_failed(raster_id: str, raster_name: str, error: Exception) -> None:
    _state[raster_id] = {"error": format_api_error(error), "name": raster_name}
    _added_while_downloading.pop(raster_id, None)  # kept: they show the error
    _update_indicators(raster_id)
    _report_failure(raster_id, raster_name, error)


def _on_terminated(raster_id: str) -> None:
    state = _state.get(raster_id)
    if state is None or "error" in state:
        return
    # Ended without data and without an error: the user canceled it
    del _state[raster_id]
    added = _added_while_downloading.pop(raster_id, set())
    project = QgsProject.instance()
    for layer_id in added:
        if project.mapLayer(layer_id) is not None:
            project.removeMapLayer(layer_id)
    _update_indicators(raster_id)


def _on_layers_added(*_args) -> None:
    for raster_id in list(_state):
        _update_indicators(raster_id)


def tooltip(raster_id: str) -> str:
    state = _state[raster_id]
    if "error" in state:
        return i18n.tr(
            "The download from Kumoy failed, so this layer is empty: {}\n"
            "Click this icon to retry."
        ).format(state["error"])
    return i18n.tr(
        "Downloading from Kumoy: {}%\nThe layer stays empty until it finishes."
    ).format(int(state["progress"]))


def _layers_of(raster_id: str) -> List[QgsMapLayer]:
    layers = []
    for layer in QgsProject.instance().mapLayers().values():
        if layer.providerType() != constants.RASTER_DATA_PROVIDER_KEY:
            continue
        try:
            if parse_uri(layer.source())[1] == raster_id:
                layers.append(layer)
        except ValueError:
            continue
    return layers


def _update_indicators(raster_id: str) -> None:
    layers = _placeholders_of(raster_id)
    # Layers that read the COG (reloaded, or cached when added) need none
    download_indicator.hide([lyr for lyr in _layers_of(raster_id) if lyr not in layers])
    state = _state.get(raster_id)
    if state is None:
        download_indicator.hide(layers)
    elif "error" in state:
        name = str(state.get("name") or "")
        download_indicator.show_error(
            layers,
            tooltip(raster_id),
            lambda: download.fetch_raster(raster_id, name),
        )
    else:
        download_indicator.show_progress(
            layers, float(state["progress"]), tooltip(raster_id)
        )


def _report_failure(raster_id: str, raster_name: str, error: Exception) -> None:
    if isinstance(error, NotFoundError) and iface is not None:
        # Deleted on the server: say which one instead of a bare 404
        iface.messageBar().pushMessage(
            i18n.tr("Raster not found"),
            i18n.tr("The following raster does not exist: {}").format(raster_name),
            Qgis.Warning,
            10,
        )
        return
    handle_api_error(
        error, title=i18n.tr("Failed to download raster '{}'").format(raster_name)
    )
