"""Kumoy raster layers in the open project: add, and reload after download.

A Kumoy raster layer whose COG is not cached yet starts as an empty
placeholder (see kumoy/provider/raster_dataprovider.py) while the download
runs in the background. register() hooks the downloads so those layers come
alive by themselves once the file is there.
"""

from qgis.core import Qgis, QgsProject
from qgis.utils import iface

from ... import i18n
from ...kumoy import constants, download, raster_layer, session
from ...kumoy.api.error import NotFoundError
from ...kumoy.api.models import Raster
from ...kumoy.provider.raster_dataprovider import parse_uri
from ..error_handler import handle_api_error
from ..utils import reload_layer


def register() -> None:
    download.fetcher.ready.connect(reload_layers)
    download.fetcher.failed.connect(_report_failure)
    session.add_listener(_on_session_changed)


def unregister() -> None:
    session.remove_listener(_on_session_changed)
    for signal, slot in (
        (download.fetcher.ready, reload_layers),
        (download.fetcher.failed, _report_failure),
    ):
        try:
            signal.disconnect(slot)
        except TypeError:
            pass  # register() was not called


def add_raster_to_map(raster: Raster) -> None:
    """Add `raster` to the project once its COG is cached. Returns at once.

    The download shows in the task manager and can be canceled there (then
    nothing is added). Adding only a complete layer lets QGIS pick the right
    default style for the actual bands.
    """

    def add() -> None:
        try:
            QgsProject.instance().addMapLayer(raster_layer.create_raster_layer(raster))
        except Exception as e:
            handle_api_error(e)

    download.fetch_raster(raster.id, raster.name, on_ready=add)


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


def _on_session_changed() -> None:
    # A project opened before login (e.g. at QGIS startup, before the session
    # is loaded) could not download its rasters; retry now
    if session.is_logged_in():
        for _, raster_id, raster_name in _placeholders():
            download.fetch_raster(raster_id, raster_name)


def reload_layers(raster_id: str) -> None:
    """Reload the project's placeholder layers of `raster_id` from the cache."""
    for layer, layer_raster_id, _ in list(_placeholders()):
        if layer_raster_id == raster_id:
            reload_layer(layer, constants.RASTER_DATA_PROVIDER_KEY)


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
