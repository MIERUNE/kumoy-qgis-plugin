"""Kumoy vector layers in the open project: report sync failures, resync on login.

The vector provider syncs its cache in the background (kumoy/provider/
dataprovider.py) and only emits signals; this module turns them into user
feedback.
"""

from typing import Set

from qgis.core import QgsProject

from ... import i18n
from ...kumoy import constants, session
from ...kumoy.provider.dataprovider import sync_events
from ...kumoy.tasks import Canceled
from ..error_handler import handle_api_error
from ..utils import reload_layer

# Vectors whose failed sync has been reported and not yet recovered. A project
# with many layers fails all at once when offline: report the first only
_failed: Set[str] = set()


def register() -> None:
    sync_events.sync_failed.connect(_on_failed)
    sync_events.sync_finished.connect(_on_finished)
    session.add_listener(_on_session_changed)


def unregister() -> None:
    session.remove_listener(_on_session_changed)
    for signal, slot in (
        (sync_events.sync_failed, _on_failed),
        (sync_events.sync_finished, _on_finished),
    ):
        try:
            signal.disconnect(slot)
        except TypeError:
            pass  # register() was not called


def _on_finished(vector_id: str) -> None:
    _failed.discard(vector_id)


def _on_failed(vector_id: str, message: str, exception: object) -> None:
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
