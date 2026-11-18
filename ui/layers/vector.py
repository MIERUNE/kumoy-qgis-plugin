"""Kumoy vector layers in the open project: download state, sync failures,
resync on login.

The vector provider syncs its cache in the background (kumoy/provider/
dataprovider.py) and only emits signals; this module turns them into user
feedback.

A layer opened without a local cache stays empty and read-only until its
first download finishes, which takes minutes for large vectors. Without a
sign in the Layers panel it just looks empty (or broken), so such layers get
an indicator with the progress, or with the error when the download failed.
"""

from typing import Dict, List, Optional, Set

from qgis.core import QgsProject, QgsVectorLayer

from ... import i18n
from ...kumoy import constants, local_cache, session
from ...kumoy.api.error import format_api_error
from ...kumoy.provider.dataprovider import running_sync, sync_events
from ...kumoy.tasks import Canceled
from ..error_handler import handle_api_error
from ..utils import reload_layer
from . import download_indicator

# Per vector: download progress (0-100) while its first download runs, or the
# error message when it failed. Vectors with data have no entry
_state: Dict[str, Dict[str, object]] = {}

# Vectors whose failed sync has been reported and not yet recovered. A project
# with many layers fails all at once when offline: report the first only
_failed: Set[str] = set()


def register() -> None:
    sync_events.sync_started.connect(_on_started)
    sync_events.sync_failed.connect(_on_failed)
    sync_events.sync_finished.connect(_on_finished)
    session.add_listener(_on_session_changed)
    project = QgsProject.instance()
    # A layer can be added (or a project read) while its download runs
    project.layersAdded.connect(_on_layers_added)
    project.layerTreeRoot().addedChildren.connect(_on_layers_added)


def unregister() -> None:
    session.remove_listener(_on_session_changed)
    project = QgsProject.instance()
    for signal, slot in (
        (sync_events.sync_started, _on_started),
        (sync_events.sync_failed, _on_failed),
        (sync_events.sync_finished, _on_finished),
        (project.layersAdded, _on_layers_added),
        (project.layerTreeRoot().addedChildren, _on_layers_added),
    ):
        try:
            signal.disconnect(slot)
        except TypeError:
            pass  # register() was not called
    for vector_id in list(_state):
        del _state[vector_id]
        _update_indicators(vector_id)


def _on_started(vector_id: str) -> None:
    # Decided by the cache, not by the layers: the provider starts the sync in
    # its constructor, before its layer is in the project
    if local_cache.vector.open_cache(vector_id) is not None:
        return  # the layers show the cached data meanwhile: nothing to tell
    _state[vector_id] = {"progress": 0.0}
    task = running_sync(vector_id)
    if task is not None:
        task.progressChanged.connect(
            lambda progress, v=vector_id: _on_progress(v, progress)
        )
    _update_indicators(vector_id)


def _on_progress(vector_id: str, progress: float) -> None:
    state = _state.get(vector_id)
    if state is not None and "error" not in state:
        state["progress"] = progress
        _update_indicators(vector_id)


def _on_finished(vector_id: str) -> None:
    _failed.discard(vector_id)
    if _state.pop(vector_id, None) is not None:
        _update_indicators(vector_id)


def _on_failed(vector_id: str, message: str, exception: object) -> None:
    if vector_id in _state:
        if isinstance(exception, Canceled):
            del _state[vector_id]
        else:
            _state[vector_id] = {"error": message or format_api_error(exception)}
        _update_indicators(vector_id)
    if isinstance(exception, Canceled):
        return
    first = not _failed
    _failed.add(vector_id)
    if first and isinstance(exception, Exception):
        handle_api_error(exception, title=i18n.tr("Could not sync Kumoy data"))


def _on_session_changed() -> None:
    _failed.clear()
    if session.is_logged_in():
        sync_open_layers()


def sync_open_layers() -> None:
    """Bring the project's Kumoy vectors up to date after login.

    Layers opened while logged out (e.g. a project opened at QGIS startup,
    before the session is loaded) show their cache, or are invalid when there
    was none: sync the former and recreate the latter.
    """
    for layer in QgsProject.instance().mapLayers().values():
        if layer.providerType() != constants.DATA_PROVIDER_KEY:
            continue
        if layer.isValid():
            layer.dataProvider().sync()
        else:
            reload_layer(layer, constants.DATA_PROVIDER_KEY)


def _kumoy_vector_layers() -> List[QgsVectorLayer]:
    return [
        layer
        for layer in QgsProject.instance().mapLayers().values()
        if isinstance(layer, QgsVectorLayer)
        and layer.providerType() == constants.DATA_PROVIDER_KEY
        and layer.isValid()
    ]


def _on_layers_added(*_args) -> None:
    for vector_id in list(_state):
        _update_indicators(vector_id)


def tooltip(vector_id: str) -> Optional[str]:
    """What the indicator says, or None when the vector needs none."""
    state = _state.get(vector_id)
    if state is None:
        return None
    if "error" in state:
        return i18n.tr(
            "The download from Kumoy failed, so this layer is empty: {}\n"
            "Click this icon or use Sync Data to retry."
        ).format(state["error"])
    return i18n.tr(
        "Downloading from Kumoy: {}%\n"
        "The layer stays empty and cannot be edited until the download finishes."
    ).format(int(state["progress"]))


def _update_indicators(vector_id: str) -> None:
    """Show, update or remove the indicator on every layer of the vector."""
    layers = [
        layer
        for layer in _kumoy_vector_layers()
        if layer.dataProvider().vector_id() == vector_id
    ]
    state = _state.get(vector_id)
    waiting = [layer for layer in layers if not layer.dataProvider().has_data()]
    download_indicator.hide([layer for layer in layers if layer not in waiting])
    if state is None:
        download_indicator.hide(waiting)
    elif "error" in state:
        retry = waiting[0].dataProvider().sync if waiting else lambda: None
        download_indicator.show_error(waiting, tooltip(vector_id), retry)
    else:
        download_indicator.show_progress(
            waiting, float(state["progress"]), tooltip(vector_id)
        )
