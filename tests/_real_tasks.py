"""Real background tasks for tests (see RealTasks)."""


class RealTasks:
    """Runs kumoy.tasks.run_task for real (QgsTask worker threads).

    Tests patch the module's run_task with `run_task` to see which tasks
    start (`queue`), then `flush()` pumps the event loop until they and any
    tasks they start have finished, so callbacks run on the main thread as in
    QGIS. Work done in the task runs on a real worker thread: code that
    touches widgets or the project there fails as it would in QGIS.
    """

    def __init__(self):
        from plugin_dir.kumoy import tasks

        self._real = tasks.run_task
        self._running = tasks._running
        self.queue = []

    def run_task(self, *args, **kwargs):
        task = self._real(*args, **kwargs)
        self.queue.append(task)
        return task

    def flush(self, timeout=20.0):
        import time

        from qgis.PyQt.QtCore import QCoreApplication

        deadline = time.monotonic() + timeout
        while any(task in self._running for task in self.queue):
            assert time.monotonic() < deadline, "background tasks did not finish"
            QCoreApplication.processEvents()
            time.sleep(0.002)
        QCoreApplication.processEvents()
        self.queue.clear()

    def run_task_and_wait(self, *args, **kwargs):
        """run_task that returns once the task and its callbacks are done."""
        task = self.run_task(*args, **kwargs)
        self.flush()
        return task
