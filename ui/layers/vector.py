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
    # Layers opened while logged out show their cache; bring them up to date
    if session.is_logged_in():
        sync_open_layers()


def sync_open_layers() -> None:
    for layer in QgsProject.instance().mapLayers().values():
        provider = layer.dataProvider()
        if provider is not None and provider.name() == constants.DATA_PROVIDER_KEY:
            provider.sync()
