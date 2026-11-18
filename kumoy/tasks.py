"""Run blocking work (API calls, file I/O) off the main thread with QgsTask.

`fn` runs in a worker thread and must not touch widgets, iface or the open
QgsProject. The callbacks run on the main thread once it ends.
"""

from typing import Any, Callable, Dict, Optional, Set

from qgis.core import QgsApplication, QgsTask

from .api.error import AppError

# QgsTaskManager does not keep the Python wrapper alive; without this the
# task (and its callbacks) can be garbage collected while running
_running: Set["FunctionTask"] = set()


class Canceled(Exception):
    """Raised by work that stopped because the task was canceled."""


class FunctionTask(QgsTask):
    def __init__(
        self,
        description: str,
        fn: Callable[["FunctionTask"], Any],
        on_success: Optional[Callable[[Any], None]],
        on_error: Optional[Callable[[Exception], None]],
        can_cancel: bool,
    ):
        flags = QgsTask.CanCancel if can_cancel else QgsTask.Flags()
        super().__init__(description, flags)
        self._fn = fn
        self._on_success = on_success
        self._on_error = on_error
        self.result: Any = None
        self.exception: Optional[Exception] = None

    def run(self) -> bool:
        try:
            self.result = self._fn(self)
            return True
        except Exception as e:  # handed to on_error on the main thread
            self.exception = e
            return False

    def finished(self, ok: bool) -> None:
        _running.discard(self)
        if ok:
            if self._on_success is not None:
                self._on_success(self.result)
            return
        if self.isCanceled() or isinstance(self.exception, Canceled):
            return  # the user asked for it; nothing to report
        if self._on_error is not None:
            self._on_error(self.exception or AppError("Task failed"))

    def check_canceled(self) -> None:
        if self.isCanceled():
            raise Canceled()


def run_task(
    description: str,
    fn: Callable[[FunctionTask], Any],
    on_success: Optional[Callable[[Any], None]] = None,
    on_error: Optional[Callable[[Exception], None]] = None,
    can_cancel: bool = False,
    properties: Optional[Dict[str, Any]] = None,
) -> FunctionTask:
    """Start `fn(task)` in the background and return the task.

    `task.setProgress(0-100)` and `task.check_canceled()` are available to fn.
    Canceled tasks call neither callback. `properties` are set on the task
    before it is added, so that QgsTaskManager.taskAdded listeners see them.
    """
    task = FunctionTask(description, fn, on_success, on_error, can_cancel)
    for name, value in (properties or {}).items():
        task.setProperty(name, value)
    _running.add(task)
    QgsApplication.taskManager().addTask(task)
    return task
