"""ui/error_handler with real QgsTask worker threads (no thread stubs)."""

import time

import pytest
from qgis.core import QgsApplication, QgsTask
from qgis.PyQt.QtCore import QCoreApplication, QThread


def pump_until(condition, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        QCoreApplication.processEvents()
        time.sleep(0.01)


@pytest.fixture
def error_handler(qgis_app, qgis_plugin_path):
    from plugin_dir.ui import error_handler

    error_handler.init_main_thread_dispatch()
    return error_handler


class _Task(QgsTask):
    def __init__(self, fn):
        super().__init__("test", QgsTask.Flags())
        self.fn = fn

    def run(self):
        self.fn()
        return True


def test_run_on_main_thread_from_worker_threads(error_handler):
    main = QgsApplication.instance().thread()
    ran_on = []
    tasks = []
    for _ in range(3):
        # The callback records the thread it really ran on
        task = _Task(
            lambda: error_handler.run_on_main_thread(
                lambda: ran_on.append(QThread.currentThread() == main)
            )
        )
        tasks.append(task)
        QgsApplication.taskManager().addTask(task)
    pump_until(lambda: len(ran_on) == 3)
    assert ran_on == [True, True, True]


def test_401_never_runs_the_session_dialog_inline(error_handler, monkeypatch):
    from plugin_dir.kumoy.api.error import UnauthorizedError

    calls = []
    monkeypatch.setattr(error_handler, "_session_expired", lambda *_: calls.append(1))
    error_handler.handle_api_error(UnauthorizedError("Unauthorized"))
    # Called on the main thread, yet deferred to the event loop: callers may
    # be inside QgsProject.read()/write() or a Browser rebuild
    assert calls == []
    pump_until(lambda: calls == [1])


def test_401_for_an_earlier_login_keeps_the_current_one(error_handler, monkeypatch):
    from plugin_dir.kumoy import session
    from plugin_dir.kumoy.api.error import UnauthorizedError

    ended = []
    monkeypatch.setattr(error_handler, "end_session", lambda: ended.append(1))
    monkeypatch.setattr(error_handler, "refresh_kumoy_browser", lambda: None)
    monkeypatch.setattr(error_handler, "iface", None)
    monkeypatch.setattr(session, "_token", "new")

    old = UnauthorizedError("Unauthorized")
    old.rejected_token = "old"  # sent before the user logged in again
    error_handler._session_expired(old.rejected_token)
    assert ended == []

    error_handler._session_expired("new")
    assert ended == [1]
