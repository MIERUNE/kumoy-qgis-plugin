"""UI shell: Browser items, logout and the project dialog, with a mocked API.

Modules of other areas that the shell imports (map items, processing dialog
helpers, caches) are replaced by stubs so these tests only exercise the
shell. Background tasks run through a fake run_task that queues them, so a
test can check that nothing touched the network before it flushes the queue.
"""

import sys
import types

import pytest
from qgis.core import QgsDataItem, QgsProject

from plugin_dir.kumoy.api import models
from plugin_dir.kumoy.api.error import NetworkError, NotFoundError, UnauthorizedError

ORG = models.OrganizationDetail(id="org1", name="Org", role="OWNER")
PROJECT = models.ProjectDetail(id="p1", name="Proj", role="ADMIN", teamId="t1")


class FakeCache:
    def __init__(self):
        self.cleared = []
        self.total_calls = 0

    def get_cache_size(self, resource_id):
        return 0

    def get_total_cache_size(self):
        self.total_calls += 1
        return 0

    def clear(self, resource_id):
        self.cleared.append(resource_id)
        return True

    def clear_all(self):
        return True


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))


def forget_module(monkeypatch, name):
    """Drop `name` so it is imported again; both the sys.modules entry and the
    attribute on its package are restored after the test."""
    parent_name, _, child = name.rpartition(".")
    parent = sys.modules.get(parent_name)
    if parent is not None:
        monkeypatch.setattr(parent, child, getattr(parent, child, None), raising=False)
    if name in sys.modules:
        monkeypatch.delitem(sys.modules, name)


@pytest.fixture
def shell(qgis_app, qgis_plugin_path, monkeypatch):
    """Import the shell modules against stubs; returns a namespace."""
    from plugin_dir import kumoy
    from plugin_dir.kumoy import session, settings_manager, tasks
    from plugin_dir.ui import browser

    # Modules imported against the stubs must not leak into other tests
    modules_before = set(sys.modules)
    from ._real_tasks import RealTasks

    fake_tasks = RealTasks()
    monkeypatch.setattr(tasks, "run_task", fake_tasks.run_task)

    caches = types.SimpleNamespace(vector=FakeCache(), raster=FakeCache())
    local_cache = types.ModuleType("plugin_dir.kumoy.local_cache")
    local_cache.vector = caches.vector
    local_cache.raster = caches.raster
    monkeypatch.setitem(sys.modules, "plugin_dir.kumoy.local_cache", local_cache)
    monkeypatch.setattr(kumoy, "local_cache", local_cache, raising=False)

    from plugin_dir.processing import close_all_processing_dialogs as close_mod

    closed = Recorder()
    monkeypatch.setattr(close_mod, "close_all_processing_dialogs", closed)

    # Re-import the shell so it binds the stubs and the fake run_task
    shell_modules = [
        "plugin_dir.ui.utils",
        "plugin_dir.ui.account_actions",
        "plugin_dir.ui.browser.utils",
        "plugin_dir.ui.browser.vector",
        "plugin_dir.ui.browser.raster",
        "plugin_dir.ui.browser.root",
        "plugin_dir.ui.browser.gui_provider",
        "plugin_dir.ui.dialog_project_edit",
        "plugin_dir.ui.dialog_project_select",
        "plugin_dir.ui.dialog_account",
        "plugin_dir.ui.dialog_login",
    ]
    for module_name in shell_modules:
        forget_module(monkeypatch, module_name)
    import importlib

    # ui.utils is "ui_utils"; everything else by its last name part
    mods = {
        ("ui_utils" if m == "plugin_dir.ui.utils" else m.rsplit(".", 1)[1]): (
            importlib.import_module(m)
        )
        for m in shell_modules
    }

    refreshes = Recorder()
    errors = Recorder()
    messages = Recorder()
    successes = Recorder()
    for mod in mods.values():
        for attr, fake in (
            ("refresh_kumoy_browser", refreshes),
            ("handle_api_error", errors),
            ("push_success", successes),
        ):
            if hasattr(mod, attr):
                monkeypatch.setattr(mod, attr, fake)

    bar = types.SimpleNamespace(pushMessage=messages, pushInfo=messages)
    fake_iface = types.SimpleNamespace(
        messageBar=lambda: bar, reloadConnections=lambda: None, mainWindow=lambda: None
    )
    for mod in mods.values():
        if hasattr(mod, "iface"):
            monkeypatch.setattr(mod, "iface", fake_iface)

    monkeypatch.setattr(session, "_token", None)
    monkeypatch.setattr(session, "_loaded", True)
    monkeypatch.setattr(mods["root"], "_current", None)
    settings_manager.clear_selection()
    QgsProject.instance().clear()

    yield types.SimpleNamespace(
        tasks=fake_tasks,
        caches=caches,
        closed=closed,
        refreshes=refreshes,
        errors=errors,
        messages=messages,
        successes=successes,
        session=session,
        settings=settings_manager,
        **mods,
    )
    settings_manager.reset()
    QgsProject.instance().clear()
    for name in [m for m in sys.modules if m not in modules_before]:
        if name.startswith("plugin_dir."):
            del sys.modules[name]


@pytest.fixture
def api(monkeypatch):
    """Every API function used by the shell fails unless a test sets it."""
    from plugin_dir.kumoy import api as real_api

    def unexpected(*args, **kwargs):
        raise AssertionError("unexpected API call")

    for module, names in (
        (
            "organization",
            ["get_organizations", "get_organization", "get_projects", "get_my_teams"],
        ),
        (
            "project",
            ["get_project", "create_project", "update_project", "delete_project"],
        ),
        ("vector", ["get_vectors", "delete_vector", "update_vector", "create_vector"]),
        ("raster", ["get_rasters", "delete_raster", "update_raster"]),
        ("user", ["get_me", "get_public_params"]),
        ("auth", ["sign_out"]),
    ):
        for name in names:
            monkeypatch.setattr(getattr(real_api, module), name, unexpected)
    return real_api


def log_in(shell, monkeypatch, project=True):
    monkeypatch.setattr(shell.session, "_token", "token")
    if project:
        shell.settings.select_project(ORG.id, PROJECT.id)


# --- Browser root ------------------------------------------------------------


class TestRoot:
    def test_init_makes_no_api_call(self, shell, api):
        shell.root.RootCollection()  # api fixture raises on any call

    def test_logged_out_offers_login(self, shell, api):
        children = shell.root.RootCollection().createChildren()
        assert [c.name() for c in children] == ["Log in…"]
        assert isinstance(children[0], shell.utils.ActionItem)

    def test_no_project_offers_selection(self, shell, api, monkeypatch):
        log_in(shell, monkeypatch, project=False)
        children = shell.root.RootCollection().createChildren()
        assert [c.name() for c in children] == ["Select project…"]

    def test_project_children_title_and_role_cache(self, shell, api, monkeypatch):
        log_in(shell, monkeypatch)
        monkeypatch.setattr(api.organization, "get_organization", lambda i: ORG)
        monkeypatch.setattr(api.project, "get_project", lambda i: PROJECT)
        root = shell.root.RootCollection()

        children = root.createChildren()

        assert [c.name() for c in children] == ["Maps", "Vectors", "Rasters"]
        assert isinstance(children[1], shell.vector.VectorRoot)
        assert isinstance(children[2], shell.raster.RasterRoot)
        assert children[1].project is PROJECT
        assert root.name() == "Kumoy: Proj(Org)"
        assert shell.root.current_project() is PROJECT
        # A project selected later is not mistaken for the loaded one
        shell.settings.select_project(ORG.id, "other")
        assert shell.root.current_project() is None

    def test_load_error_is_an_item_with_reason(self, shell, api, monkeypatch):
        log_in(shell, monkeypatch)

        def fail(i):
            raise NetworkError("offline")

        monkeypatch.setattr(api.organization, "get_organization", fail)
        root = shell.root.RootCollection()
        children = root.createChildren()

        assert isinstance(children[0], shell.utils.ErrorItem)
        assert "offline" in children[0].toolTip()
        assert children[1].name() == "Select project…"  # not a dead end
        assert shell.errors.calls == []  # no dialog while browsing
        assert root.name() == "Kumoy"

    def test_401_goes_to_error_handler(self, shell, api, monkeypatch):
        log_in(shell, monkeypatch)

        def fail(i):
            raise UnauthorizedError("Unauthorized")

        monkeypatch.setattr(api.organization, "get_organization", fail)
        shell.root.RootCollection().createChildren()
        assert len(shell.errors.calls) == 1


# --- Vector / raster folders ----------------------------------------------------


class TestResourceRoot:
    def _root(self, shell, cls):
        return cls(None, "Vectors", "kumoy:/p1/vectors", ORG, PROJECT)

    def test_lists_vectors(self, shell, api, monkeypatch):
        vectors = [
            models.Vector(id="v1", name="A", type="POINT", projectId="p1"),
            models.Vector(id="v2", name="B", type="POLYGON", projectId="p1"),
        ]
        monkeypatch.setattr(api.vector, "get_vectors", lambda pid: vectors)
        children = self._root(shell, shell.vector.VectorRoot).createChildren()
        assert [c.name() for c in children] == ["A", "B"]
        assert children[0].vector is vectors[0]
        assert children[0].role == "ADMIN"

    def test_empty_and_error(self, shell, api, monkeypatch):
        monkeypatch.setattr(api.raster, "get_rasters", lambda pid: [])
        root = self._root(shell, shell.raster.RasterRoot)
        assert [c.name() for c in root.createChildren()] == [
            "No rasters found in this project"
        ]

        def fail(pid):
            raise NotFoundError("Not Found")

        monkeypatch.setattr(api.raster, "get_rasters", fail)
        (item,) = root.createChildren()
        assert item.name() == "Error loading rasters"
        assert "Not Found" in item.toolTip()

    def test_menu_does_not_walk_the_cache(self, shell, api):
        from qgis.PyQt.QtWidgets import QMenu

        menu = QMenu()
        actions = self._root(shell, shell.vector.VectorRoot).actions(menu)
        assert [a.text() for a in actions] == [
            "Create Vector",
            "Upload Vector",
            "Clear Vector Cache Data",
        ]
        assert shell.caches.vector.total_calls == 0

    def test_viewer_gets_no_edit_actions(self, shell, api):
        from qgis.PyQt.QtWidgets import QMenu

        viewer = models.ProjectDetail(id="p1", name="Proj", role="MEMBER")
        root = shell.raster.RasterRoot(None, "Rasters", "kumoy:/p1/r", ORG, viewer)
        menu = QMenu()
        assert [a.text() for a in root.actions(menu)] == ["Clear Raster Cache Data"]


# --- Delete ------------------------------------------------------------------


class TestDelete:
    def _items(self, shell, n):
        return [
            shell.vector.VectorItem(
                None,
                f"kumoy:/p1/vectors/v{i}",
                models.Vector(id=f"v{i}", name=f"V{i}", type="POINT", projectId="p1"),
                "ADMIN",
            )
            for i in range(n)
        ]

    def test_confirmation_mentions_loaded_layers(self, shell, api, monkeypatch):
        texts = []
        monkeypatch.setattr(
            shell.utils, "confirm", lambda parent, title, text: texts.append(text)
        )
        monkeypatch.setattr(shell.utils, "layers_of", lambda *a: [object()])
        shell.utils.delete(self._items(shell, 1))
        assert "1 layer(s) in the current QGIS project will be removed" in texts[0]
        assert shell.tasks.queue == []  # declined: nothing deleted

    def test_reports_failures_and_stops_on_401(self, shell, api, monkeypatch):
        monkeypatch.setattr(shell.utils, "confirm", lambda *a: True)
        monkeypatch.setattr(shell.utils, "layers_of", lambda *a: [])
        attempted = []

        def delete_vector(vector_id):
            attempted.append(vector_id)
            if vector_id == "v1":
                raise NotFoundError("gone")
            if vector_id == "v2":
                raise UnauthorizedError("Unauthorized")

        monkeypatch.setattr(api.vector, "delete_vector", delete_vector)
        shell.utils.delete(self._items(shell, 4))
        shell.tasks.flush()

        assert attempted == ["v0", "v1", "v2"]  # v3 not tried after the 401
        assert shell.caches.vector.cleared == ["v0"]
        assert len(shell.errors.calls) == 1  # the 401
        ((args, _),) = shell.messages.calls
        assert "Deleted 1 of 4." in args[1]
        assert "V1" in args[1]
        assert shell.successes.calls == []

    def test_success_message(self, shell, api, monkeypatch):
        monkeypatch.setattr(shell.utils, "confirm", lambda *a: True)
        monkeypatch.setattr(shell.utils, "layers_of", lambda *a: [])
        monkeypatch.setattr(api.vector, "delete_vector", lambda i: None)
        shell.utils.delete(self._items(shell, 2))
        shell.tasks.flush()
        assert (
            shell.successes.calls[0][0][0]
            == "2 vectors have been deleted successfully."
        )


def test_uri_param(shell):
    source = "project_id=p1;vector_id=v1;vector_name=a=b;vector_type=POINT;"
    assert shell.ui_utils.uri_param(source, "vector_id") == "v1"
    assert shell.ui_utils.uri_param(source, "vector_name") == "a=b"
    assert shell.ui_utils.uri_param(source, "raster_id") == ""


# --- Logout ------------------------------------------------------------------


class TestLogout:
    def test_revokes_and_clears(self, shell, api, monkeypatch):
        log_in(shell, monkeypatch)
        signed_out = []
        monkeypatch.setattr(
            api.auth, "sign_out", lambda t, r: signed_out.append((t, r))
        )
        assert shell.account_actions.logout()
        shell.tasks.flush()

        assert signed_out == [("token", None)]
        assert not shell.session.is_logged_in()
        assert shell.settings.selected_project_id() == ""
        assert len(shell.closed.calls) == 1
        assert len(shell.refreshes.calls) == 1

    def test_sign_out_failure_still_logs_out(self, shell, api, monkeypatch):
        log_in(shell, monkeypatch)

        def fail(token, refresh_token):
            raise NetworkError("offline")

        monkeypatch.setattr(api.auth, "sign_out", fail)
        shell.account_actions.logout()
        shell.tasks.flush()
        assert not shell.session.is_logged_in()
        assert shell.errors.calls == []

    def test_open_map_asks_and_closes(self, shell, api, monkeypatch):
        log_in(shell, monkeypatch)
        monkeypatch.setattr(api.auth, "sign_out", lambda t, r: None)
        QgsProject.instance().setFileName("kumoy:m1")
        answers = [False, True]
        monkeypatch.setattr(shell.account_actions, "confirm", lambda *a: answers.pop(0))

        assert not shell.account_actions.logout()  # declined
        assert shell.session.is_logged_in()

        assert shell.account_actions.logout()
        assert QgsProject.instance().fileName() == ""

    def test_forced_logout_keeps_project(self, shell, api, monkeypatch):
        log_in(shell, monkeypatch)
        monkeypatch.setattr(api.auth, "sign_out", lambda t, r: None)
        QgsProject.instance().setFileName("kumoy:m1")
        monkeypatch.setattr(
            shell.account_actions, "confirm", lambda *a: pytest.fail("asked")
        )
        shell.account_actions.logout(ask=False)
        assert not shell.session.is_logged_in()
        assert QgsProject.instance().fileName() == "kumoy:m1"


class TestVersionCheck:
    def test_not_run_when_logged_out(self, shell, api):
        shell.account_actions.check_plugin_version()
        assert shell.tasks.queue == []

    def test_incompatible_version_logs_out(self, shell, api, monkeypatch):
        log_in(shell, monkeypatch)
        monkeypatch.setattr(
            api.user,
            "get_public_params",
            lambda: models.PublicParams(minQgisPluginVersion="v999.0.0"),
        )
        monkeypatch.setattr(api.auth, "sign_out", lambda t, r: None)
        monkeypatch.setattr(
            shell.account_actions, "read_plugin_version", lambda: "v1.0.0"
        )
        shell.account_actions.check_plugin_version()
        shell.tasks.flush()
        assert not shell.session.is_logged_in()
        assert "v999.0.0" in shell.messages.calls[-1][0][1]

    def test_unreachable_server_is_a_message_bar_warning(self, shell, api, monkeypatch):
        log_in(shell, monkeypatch)

        def fail():
            raise NetworkError("offline")

        monkeypatch.setattr(api.user, "get_public_params", fail)
        shell.account_actions.check_plugin_version()
        shell.tasks.flush()
        assert shell.session.is_logged_in()
        assert len(shell.messages.calls) == 1


# --- Project dialog ------------------------------------------------------------


def _org(org_id, deleting=None):
    return models.OrganizationWithRole(
        id=org_id, name=org_id.upper(), role="ADMIN", scheduledDeletionAt=deleting
    )


def _project(project_id, team_id="t1"):
    return models.ProjectInOrganization(
        id=project_id, name=project_id, teamId=team_id, updatedAt=""
    )


class TestProjectDialog:
    @pytest.fixture
    def org_api(self, api, monkeypatch):
        calls = {"projects": [], "teams": []}
        monkeypatch.setattr(api.user, "get_me", lambda: models.User(id="u", name="Ann"))
        monkeypatch.setattr(
            api.organization,
            "get_organizations",
            lambda: [
                _org("o1"),
                _org("o2"),
                _org("o3", deleting="2026-12-01T00:00:00Z"),
            ],
        )
        monkeypatch.setattr(api.organization, "get_organization", lambda i: ORG)

        def get_projects(org_id):
            calls["projects"].append(org_id)
            return [_project(f"{org_id}-a"), _project(f"{org_id}-b", "t2")]

        def get_my_teams(org_id):
            calls["teams"].append(org_id)
            return [
                models.TeamWithRole(id="t1", name="T1", role="ADMIN"),
                models.TeamWithRole(id="t2", name="T2", role="MEMBER"),
            ]

        monkeypatch.setattr(api.organization, "get_projects", get_projects)
        monkeypatch.setattr(api.organization, "get_my_teams", get_my_teams)
        return calls

    def _project_ids(self, dialog):
        from plugin_dir.pyqt_version import QT_USER_ROLE

        proxy = dialog.project_section["proxy"]
        return [
            proxy.index(i, 0).data(QT_USER_ROLE).id for i in range(proxy.rowCount())
        ]

    def test_shows_before_loading_then_loads_once(self, shell, org_api, monkeypatch):
        log_in(shell, monkeypatch, project=False)
        shell.settings.select_project("o2", "o2-b")

        dialog = shell.dialog_project_select.ProjectSelectDialog()
        assert org_api["projects"] == []  # nothing fetched in the constructor
        assert self._project_ids(dialog) == []

        shell.tasks.flush()

        assert org_api == {"projects": ["o2"], "teams": ["o2"]}
        assert self._project_ids(dialog) == ["o2-a", "o2-b"]
        assert dialog.selected_project.id == "o2-b"
        assert dialog.button_panel["new_project_btn"].isEnabled()
        assert shell.settings.get("last_organization_id") == "o2"

    def test_storage_usage_accepts_fractional_units(
        self, shell, org_api, api, monkeypatch
    ):
        # The API sends numbers; from_dict turns them into floats, which
        # QProgressBar.setMaximum() rejects
        detail = models.from_dict(
            models.OrganizationDetail,
            {
                "id": "org1",
                "name": "Org",
                "availableStorageUnits": 30,
                "usage": {"usedStorageUnits": 12.5},
            },
        )
        monkeypatch.setattr(api.organization, "get_organization", lambda i: detail)
        log_in(shell, monkeypatch, project=False)
        shell.settings.select_project("o1", "")

        dialog = shell.dialog_project_select.ProjectSelectDialog()
        shell.tasks.flush()

        bar = dialog.org_details_panel["usage_widgets"]["storage"]["progress"]
        assert (bar.maximum(), bar.value()) == (30, 13)

    def test_changing_org_loads_it_and_drops_stale_results(
        self, shell, org_api, monkeypatch
    ):
        log_in(shell, monkeypatch, project=False)
        dialog = shell.dialog_project_select.ProjectSelectDialog()
        shell.tasks.flush()
        combo = dialog.account_org_panel["org_combo"]

        combo.setCurrentIndex(1)  # o2, then o1 again before o2 arrives
        combo.setCurrentIndex(0)
        shell.tasks.flush()

        assert self._project_ids(dialog) == ["o1-a", "o1-b"]
        assert shell.settings.get("last_organization_id") == "o1"

    def test_scheduled_deletion_does_not_load(self, shell, org_api, monkeypatch):
        log_in(shell, monkeypatch, project=False)
        shell.settings.store("last_organization_id", "o3")
        dialog = shell.dialog_project_select.ProjectSelectDialog()
        shell.tasks.flush()
        assert org_api["projects"] == []
        assert self._project_ids(dialog) == []

    def test_one_error_message(self, shell, org_api, api, monkeypatch):
        log_in(shell, monkeypatch, project=False)

        def fail(org_id):
            raise NetworkError("offline")

        monkeypatch.setattr(api.organization, "get_projects", fail)
        shell.dialog_project_select.ProjectSelectDialog()
        shell.tasks.flush()
        assert len(shell.errors.calls) == 1

    def test_double_click_selects(self, shell, org_api, monkeypatch):
        log_in(shell, monkeypatch, project=False)
        dialog = shell.dialog_project_select.ProjectSelectDialog()
        shell.tasks.flush()
        proxy = dialog.project_section["proxy"]
        dialog.project_section["grid"].doubleClicked.emit(proxy.index(1, 3))
        assert dialog.result() == 1
        assert dialog.selected_organization_id == "o1"
        assert dialog.selected_project.id == "o1-b"

    def test_filter_and_view_switch_keep_the_selection(
        self, shell, org_api, monkeypatch
    ):
        log_in(shell, monkeypatch, project=False)
        shell.settings.select_project("o1", "o1-b")
        dialog = shell.dialog_project_select.ProjectSelectDialog()
        shell.tasks.flush()
        section = dialog.project_section

        section["view_buttons"].button(1).click()  # table
        assert section["stack"].currentWidget() is section["table"]
        assert shell.settings.get("project_view") == "table"
        assert dialog.selected_project.id == "o1-b"

        section["team_combo"].setCurrentIndex(section["team_combo"].findData("t1"))
        assert self._project_ids(dialog) == ["o1-a"]
        assert dialog.selected_project is None  # o1-b is filtered out
        section["team_combo"].setCurrentIndex(0)
        section["search_input"].setText("-B")
        assert self._project_ids(dialog) == ["o1-b"]

    def test_deleting_selected_project_resets_selection(
        self, shell, org_api, api, monkeypatch
    ):
        log_in(shell, monkeypatch, project=False)
        shell.settings.select_project("o1", "o1-a")
        dialog = shell.dialog_project_select.ProjectSelectDialog()
        shell.tasks.flush()
        monkeypatch.setattr(shell.dialog_project_select, "confirm", lambda *a: True)
        deleted = []
        monkeypatch.setattr(api.project, "delete_project", deleted.append)
        get_projects = api.organization.get_projects
        monkeypatch.setattr(
            api.organization,
            "get_projects",
            lambda o: [p for p in get_projects(o) if p.id not in deleted],
        )

        dialog.delete_project(dialog.selected_project)
        shell.tasks.flush()

        assert deleted == ["o1-a"]
        assert shell.settings.selected_project_id() == ""
        assert len(shell.refreshes.calls) == 1
        assert self._project_ids(dialog) == ["o1-b"]
        assert dialog.selected_project is None


# --- Plugin startup ----------------------------------------------------------


@pytest.fixture
def plugin(shell, api, monkeypatch):
    """KumoyPlugin with a fake iface and the other areas' modules stubbed."""
    from qgis.core import QgsProcessingProvider
    from qgis.PyQt.QtCore import QObject, pyqtSignal
    from qgis.PyQt.QtWidgets import QMainWindow, QMenu

    class ProcessingProvider(QgsProcessingProvider):
        def id(self):
            return "kumoy_shell_test"

        def name(self):
            return "stub"

        def loadAlgorithms(self):
            pass

    stubs = {
        "plugin_dir.kumoy.provider.dataprovider_metadata": {
            "KumoyProviderMetadata": object
        },
        "plugin_dir.kumoy.provider.raster_dataprovider_metadata": {
            "KumoyRasterProviderMetadata": object
        },
        "plugin_dir.processing.provider": {
            "KumoyProcessingProvider": ProcessingProvider
        },
        "plugin_dir.ui.layers.convert": {"on_convert_layer_clicked": Recorder()},
    }
    for name, attrs in stubs.items():
        module = types.ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)
    forget_module(monkeypatch, "plugin_dir.plugin")
    import importlib

    plugin_module = importlib.import_module("plugin_dir.plugin")
    registry = types.SimpleNamespace(registerProvider=lambda m: True)
    monkeypatch.setattr(
        plugin_module,
        "QgsProviderRegistry",
        types.SimpleNamespace(instance=lambda: registry),
    )

    class LayerTreeView(QObject):
        contextMenuAboutToShow = pyqtSignal(QMenu)

    class Iface(QObject):
        initializationCompleted = pyqtSignal()

        def __init__(self):
            super().__init__()
            self.window = QMainWindow()  # never shown: QGIS is "starting"
            self.menu = QMenu()
            self.view = LayerTreeView()

        def mainWindow(self):
            return self.window

        def pluginMenu(self):
            return self.menu

        def layerTreeView(self):
            return self.view

    loads = Recorder()
    monkeypatch.setattr(shell.session, "load", loads)
    iface = Iface()
    instance = plugin_module.KumoyPlugin(iface)
    yield types.SimpleNamespace(plugin=instance, iface=iface, loads=loads)
    instance.unload()


class TestStartup:
    def test_init_gui_waits_for_qgis_to_start(self, shell, plugin):
        plugin.plugin.initGui()  # the api fixture fails on any request

        assert plugin.loads.calls == []  # may prompt: not during startup
        assert shell.tasks.queue == []
        assert shell.refreshes.calls == []

        plugin.iface.initializationCompleted.emit()

        assert len(plugin.loads.calls) == 1
        assert shell.tasks.queue == []  # logged out: no version check
        assert len(shell.refreshes.calls) == 1

    def test_version_check_after_startup_when_logged_in(
        self, shell, plugin, monkeypatch
    ):
        monkeypatch.setattr(shell.session, "_token", "token")
        plugin.plugin.initGui()
        plugin.iface.initializationCompleted.emit()
        assert len(shell.tasks.queue) == 1

    def test_menu_follows_login_state(self, shell, plugin, monkeypatch):
        plugin.plugin.initGui()
        p = plugin.plugin
        assert p.login_action.isVisible() and not p.logout_action.isVisible()

        monkeypatch.setattr(shell.session, "_token", "token")
        plugin.iface.menu.aboutToShow.emit()
        assert not p.login_action.isVisible() and p.logout_action.isVisible()
