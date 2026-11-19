"""Integration tests against a running Kumoy server (see README.md).

Skipped unless KUMOY_E2E_URL and KUMOY_E2E_TEAM_ID are set. Nothing in
kumoy.api is patched: the plugin talks HTTP to the server, presigned uploads
and downloads included. The server is not started or seeded here; logging in
goes through the plugin's device flow, approved by a person in the browser.
"""

import os
import time
import uuid
from typing import Callable

import pytest

ENV = ("KUMOY_E2E_URL", "KUMOY_E2E_TEAM_ID")
URL = os.environ.get("KUMOY_E2E_URL", "").rstrip("/")


def pytest_collection_modifyitems(config, items):
    missing = [name for name in ENV if not os.environ.get(name)]
    if not missing:
        return
    skip = pytest.mark.skip(reason=f"set {', '.join(missing)} to run")
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(skip)


def pump(seconds: float = 0.0) -> None:
    """Run the Qt event loop for `seconds` (QgsTask callbacks, timers)."""
    from qgis.PyQt.QtCore import QCoreApplication

    end = time.monotonic() + seconds
    while True:
        QCoreApplication.processEvents()
        if time.monotonic() >= end:
            return
        time.sleep(0.01)


def wait_until(cond: Callable[[], bool], timeout: float = 30, what: str = "") -> None:
    """Pump the event loop until cond() holds; fail after `timeout` seconds."""
    from qgis.core import QgsApplication

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        pump(0.05)
        if cond():
            return
    tasks = [t.description() for t in QgsApplication.taskManager().activeTasks()]
    pytest.fail(f"Timed out waiting for {what or cond} (active tasks: {tasks})")


def wait_for_tasks(timeout: float = 60) -> None:
    from qgis.core import QgsApplication

    wait_until(
        lambda: QgsApplication.taskManager().countActiveTasks() == 0,
        timeout,
        "background tasks",
    )


def interactive_login(config):
    """Log in through the plugin's device flow, approved by a person.

    Prints the URL and code (past pytest's output capture) and waits until
    they are approved in the browser. Returns the plugin's api.auth.Tokens.
    """
    from plugin_dir.kumoy import api

    code = api.auth.request_device_code()
    timeout = float(os.environ.get("KUMOY_E2E_LOGIN_TIMEOUT", "300"))
    _tell(
        config,
        f"\nKumoy login: open {code.verification_url}\n"
        f"and approve the code {code.user_code} within {timeout:.0f} s...",
    )
    interval = code.interval
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(interval)
        try:
            tokens = api.auth.poll_device_token(code.device_code)
        except api.error.AppError as e:
            if e.error != "slow_down":
                raise
            interval += 5
            continue
        if tokens:
            return tokens
    pytest.fail("the login code was not approved in time")


def _tell(config, message: str) -> None:
    capture = config.pluginmanager.getplugin("capturemanager")
    with capture.global_and_fixture_disabled():
        print(message, flush=True)


def require_interactive() -> None:
    """Tests that need another login (each asks for one more approval)."""
    if os.environ.get("KUMOY_E2E_INTERACTIVE") != "1":
        pytest.skip("needs another browser approval: set KUMOY_E2E_INTERACTIVE=1")


@pytest.fixture(autouse=True)
def dialogs(monkeypatch):
    """Modal message boxes would hang the run: record them and answer No."""
    from qgis.PyQt.QtWidgets import QMessageBox

    from plugin_dir.pyqt_version import Q_MESSAGEBOX_STD_BUTTON

    shown = []

    def static(kind):
        def show(_parent, title, text, *_args, **_kwargs):
            shown.append((kind, title, text))
            return Q_MESSAGEBOX_STD_BUTTON.No

        return staticmethod(show)

    for kind in ("question", "warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, kind, static(kind))

    def exec_(box):
        shown.append(("exec", box.windowTitle(), box.text()))
        return 0

    monkeypatch.setattr(QMessageBox, "exec", exec_)
    monkeypatch.setattr(QMessageBox, "exec_", exec_, raising=False)
    return shown


@pytest.fixture(scope="session")
def plugin(qgis_app, qgis_plugin_path):
    """The plugin's registrations, as initGui does them (without the GUI)."""
    from qgis.core import QgsApplication, QgsProviderRegistry

    from plugin_dir.kumoy import settings_manager
    from plugin_dir.kumoy.provider.dataprovider_metadata import KumoyProviderMetadata
    from plugin_dir.kumoy.provider.raster_dataprovider_metadata import (
        KumoyRasterProviderMetadata,
    )
    from plugin_dir.processing.provider import KumoyProcessingProvider
    from plugin_dir.ui import project_storage

    settings_manager.set_custom_server(True, URL)
    registry = QgsProviderRegistry.instance()
    assert registry.registerProvider(KumoyProviderMetadata()), (
        "the kumoy provider key is taken: run tests/integration on its own"
    )
    assert registry.registerProvider(KumoyRasterProviderMetadata())

    from processing.core.Processing import Processing

    Processing.initialize()
    provider = KumoyProcessingProvider()
    QgsApplication.processingRegistry().addProvider(provider)
    project_storage.register()
    yield
    project_storage.unregister()
    QgsApplication.processingRegistry().removeProvider(provider)


@pytest.fixture(scope="session")
def token(plugin, pytestconfig):
    """KUMOY_E2E_TOKEN, or a login approved in the browser.

    Not session.set_token(): that may ask for the QGIS master password, which
    would block headless.
    """
    from plugin_dir.kumoy import api, session

    value = os.environ.get("KUMOY_E2E_TOKEN")
    if not value:
        # Only the access token: a refresh would rotate the refresh token and
        # make the exported one unusable
        value = interactive_login(pytestconfig).access_token
        _tell(
            pytestconfig,
            "Logged in. To skip the login next time (valid for 1 hour):\n"
            f"  export KUMOY_E2E_TOKEN={value}",
        )
    session._token = value
    try:
        api.user.get_me()
    except api.error.UnauthorizedError:
        pytest.exit("KUMOY_E2E_TOKEN is expired or revoked: unset it to log in")
    yield value
    session._token = None


@pytest.fixture(scope="session")
def project(token):
    """A fresh Kumoy project in the test team, selected in the plugin and
    deleted at the end (an interrupted run can leave an "e2e-..." project)."""
    from plugin_dir.kumoy import api, settings_manager

    created = api.project.create_project(
        os.environ["KUMOY_E2E_TEAM_ID"], f"e2e-{uuid.uuid4().hex[:8]}"
    )
    detail = api.project.get_project(created.id)
    settings_manager.select_project(detail.team.organizationId, detail.id)
    yield detail
    from plugin_dir.kumoy import session

    if session.get_token():
        api.project.delete_project(created.id)
