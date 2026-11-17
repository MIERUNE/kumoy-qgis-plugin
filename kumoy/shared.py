from typing import Callable, TypeVar

from qgis.core import QgsApplication

T = TypeVar("T")


def shared(name: str, factory: Callable[[], T]) -> T:
    """One instance per QGIS session, surviving plugin reloads and upgrades.

    Data providers cannot be unregistered, so after a reload QGIS keeps
    creating layers with the previous module's provider classes. Signal hubs
    those providers emit on must be the same objects the reloaded UI connects
    to, so they live on the application instead of in a module global.
    """
    app = QgsApplication.instance()
    if app is None:
        return factory()
    attr = f"_kumoy_{name}"
    obj = getattr(app, attr, None)
    if obj is None:
        obj = factory()
        setattr(app, attr, obj)
    return obj
