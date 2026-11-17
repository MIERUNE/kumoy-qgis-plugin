"""The login dialog's flow and logout against the server.

Each test needs one more browser approval: run with KUMOY_E2E_INTERACTIVE=1.
"""

import pytest

from .conftest import _tell, interactive_login, require_interactive, wait_until


@pytest.fixture
def login(plugin):
    from plugin_dir.kumoy.auth_manager import DeviceLogin

    require_interactive()
    flow = DeviceLogin()
    events = []
    flow.code_received.connect(lambda code, url: events.append(("code", code, url)))
    flow.succeeded.connect(lambda token: events.append(("ok", token)))
    flow.failed.connect(lambda message: events.append(("failed", message)))
    yield flow, events
    flow.cancel()


def test_approved(login, plugin, pytestconfig):
    import os

    from plugin_dir.kumoy import api, session

    flow, events = login
    flow.start()
    wait_until(lambda: events, 30, "device code")
    kind, user_code, url = events[0]
    assert kind == "code" and user_code in url

    _tell(pytestconfig, f"\nLogin dialog test: open {url} and approve {user_code}")
    timeout = float(os.environ.get("KUMOY_E2E_LOGIN_TIMEOUT", "300"))
    wait_until(lambda: len(events) > 1, timeout, "approval in the browser")
    assert events[1][0] == "ok", events[1]

    saved = session._token
    session._token = events[1][1]
    try:
        assert api.user.get_me().email
        api.auth.sign_out(events[1][1])
    finally:
        session._token = saved


def test_logout_revokes_the_session(plugin, token, project, pytestconfig):
    """ui.account_actions.logout: local session gone, server session revoked."""
    from plugin_dir.kumoy import api, session, settings_manager
    from plugin_dir.ui import account_actions

    from .conftest import wait_for_tasks

    require_interactive()
    second = interactive_login(pytestconfig)
    try:
        session._token = second
        assert account_actions.logout(ask=False)
        assert not session.is_logged_in()
        wait_for_tasks()
        session._token = second
        with pytest.raises(api.error.UnauthorizedError):
            api.user.get_me()
    finally:
        session._token = token
        # Logging out forgets the selected project
        settings_manager.select_project(project.team.organizationId, project.id)
