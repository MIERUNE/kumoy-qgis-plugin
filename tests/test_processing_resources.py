"""Processing tools that operate on Kumoy resources (API functions are mocked).

Tool IDs, parameters and outputs are a public scripting API; these tests pin
them. Map tools are tested in test_processing_map.py.
"""

import importlib
from types import SimpleNamespace

import pytest
from qgis.core import (
    Qgis,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)


def _run(alg, parameters, context=None):
    """Run like processing.run() does, but in-process so monkeypatches apply."""
    alg.initAlgorithm()
    return alg.processAlgorithm(
        parameters, context or QgsProcessingContext(), QgsProcessingFeedback()
    )


def _alg(module, name):
    return getattr(importlib.import_module(f"plugin_dir.processing.{module}"), name)()


@pytest.fixture
def api(qgis_plugin_path):
    from plugin_dir.kumoy import api

    return api


@pytest.fixture
def local_cache(qgis_plugin_path):
    from plugin_dir.kumoy import local_cache

    return local_cache


@pytest.fixture
def base(qgis_plugin_path):
    from plugin_dir.processing import base

    return base


def _select_project(monkeypatch, project_id):
    from plugin_dir.kumoy import settings_manager

    monkeypatch.setattr(settings_manager, "selected_project_id", lambda: project_id)


@pytest.fixture(autouse=True)
def logged_in(qgis_plugin_path, api, base, monkeypatch):
    """Log in, select p1 and make every vector/raster belong to it unless overridden."""
    from plugin_dir.kumoy import session

    monkeypatch.setattr(session, "_token", "token")
    _select_project(monkeypatch, "p1")
    in_p1 = lambda _: SimpleNamespace(projectId="p1")  # noqa: E731
    monkeypatch.setattr(api.vector, "get_vector", in_p1)
    monkeypatch.setattr(api.raster, "get_raster", in_p1)
    # Background refreshes of the upload destinations must not reach the network
    monkeypatch.setattr(base, "run_task", lambda *a, **k: None)
    monkeypatch.setattr(base, "_project_choices", [])
    monkeypatch.setattr(base, "_refreshing", False)
    monkeypatch.setattr(base, "_last_refresh", -1e9)


@pytest.mark.usefixtures("qgis_plugin_path")
class TestProject:
    def test_has_no_html_output(self):
        # The Results Viewer, opened for HTML outputs on completion, makes the
        # algorithm dialog disappear along with its log
        from qgis.core import QgsProcessingOutputHtml

        alg = _alg("organization.list_organizations", "ListOrganizationsAlgorithm")
        alg.initAlgorithm()

        assert not any(
            isinstance(o, QgsProcessingOutputHtml) for o in alg.outputDefinitions()
        )

    def test_list_organizations_returns_plain_dicts(self, api, monkeypatch):
        org = api.models.from_dict(
            api.models.OrganizationWithRole,
            {
                "id": "o1",
                "name": "Org",
                "iconImage": None,
                "stripeCustomerId": None,
                "subscriptionPlan": "FREE",
                "storageUnits": 1,
                "createdAt": "",
                "updatedAt": "",
                "role": "OWNER",
            },
        )
        monkeypatch.setattr(api.organization, "get_organizations", lambda: [org])

        result = _run(
            _alg("organization.list_organizations", "ListOrganizationsAlgorithm"), {}
        )

        # The keys scripts got before the rewrite, plus iconImage
        assert result["ORGANIZATIONS"] == [
            {
                "id": "o1",
                "name": "Org",
                "iconImage": None,
                "stripeCustomerId": None,
                "subscriptionPlan": "FREE",
                "storageUnits": 1,
                "createdAt": "",
                "updatedAt": "",
                "role": "OWNER",
                "scheduledDeletionAt": None,
            }
        ]

    def test_list_projects_passes_organization_id(self, api, monkeypatch):
        captured = {}

        def fake(organization_id):
            captured["id"] = organization_id
            return []

        monkeypatch.setattr(api.organization, "get_projects", fake)

        result = _run(
            _alg("organization.list_projects", "ListProjectsAlgorithm"),
            {"ORGANIZATION_ID": " o1 "},
        )

        assert captured["id"] == "o1"
        assert result["PROJECTS"] == []

    def test_get_project_targets_selected_project(self, api, monkeypatch):
        requested = []
        monkeypatch.setattr(
            api.project,
            "get_project",
            lambda i: requested.append(i) or {"id": i, "name": "P"},
        )
        monkeypatch.setattr(
            api.vector,
            "get_vectors",
            lambda _: [{"id": "v1", "project": {"id": "p1"}}],
        )
        monkeypatch.setattr(api.raster, "get_rasters", lambda _: [{"id": "r1"}])
        monkeypatch.setattr(
            api.styledmap,
            "get_styled_maps",
            lambda _: [{"id": "m1", "project": {"id": "p1"}}],
        )

        result = _run(_alg("organization.get_project", "GetProjectAlgorithm"), {})

        assert requested == ["p1"]
        assert result["PROJECT"] == {
            "id": "p1",
            "name": "P",
            "vectors": [{"id": "v1"}],
            "rasters": [{"id": "r1"}],
            "maps": [{"id": "m1"}],
        }


@pytest.mark.usefixtures("qgis_plugin_path")
class TestOutputCompatibility:
    """Outputs keep the keys of the old API classes, parsed from server JSON."""

    PROJECT = {
        "id": "p1",
        "name": "P",
        "teamId": "t1",
        "team": {
            "id": "t1",
            "name": "T",
            "organizationId": "o1",
            "organization": {"id": "o1", "name": "O", "stripeCustomerId": None},
        },
    }

    def test_get_vector_includes_project(self, api, monkeypatch):
        detail = api.models.from_dict(
            api.models.VectorDetail,
            {
                "id": "v1",
                "name": "roads",
                "type": "LINESTRING",
                "projectId": "p1",
                "project": self.PROJECT,
                "attribution": "",
                "storageUnits": 0.5,
                "role": "ADMIN",
                "extent": [0, 0, 1, 1],
                "count": 3,
                "columns": [{"name": "a", "type": "string"}],
                "createdAt": "",
                "updatedAt": "",
            },
        )
        monkeypatch.setattr(api.vector, "get_vector", lambda _: detail)

        vector = _run(_alg("vector.get", "GetVectorAlgorithm"), {"VECTOR_ID": "v1"})[
            "VECTOR"
        ]

        assert {
            "id",
            "name",
            "type",
            "projectId",
            "project",
            "attribution",
            "storageUnits",
            "createdAt",
            "updatedAt",
            "role",
            "extent",
            "count",
            "columns",
        } <= set(vector)
        assert vector["project"]["team"]["organization"]["id"] == "o1"
        assert vector["columns"] == [{"name": "a", "type": "string"}]

    def test_update_vector_includes_uri_and_bytes(self, api, monkeypatch):
        updated = api.models.from_dict(
            api.models.VectorMutationResult,
            {
                "id": "v1",
                "name": "n",
                "uri": "table",
                "type": "POINT",
                "projectId": "p1",
                "attribution": None,
                "bytes": 10,
                "createdAt": "",
                "updatedAt": "",
            },
        )
        monkeypatch.setattr(api.vector, "update_vector", lambda *_, **__: updated)

        vector = _run(
            _alg("vector.update", "UpdateVectorAlgorithm"),
            {"VECTOR_ID": "v1", "NAME": "n"},
        )["VECTOR"]

        assert vector["uri"] == "table"
        assert vector["bytes"] == 10

    def test_list_rasters_includes_bytes(self, api, monkeypatch):
        raster = api.models.from_dict(
            api.models.Raster,
            {"id": "r1", "name": "dem", "projectId": "p1", "bytes": 42},
        )
        monkeypatch.setattr(api.raster, "get_rasters", lambda _: [raster])

        rasters = _run(
            _alg("raster.list", "ListRastersAlgorithm"), {"PROJECT_ID": "p1"}
        )["RASTERS"]

        assert rasters[0]["bytes"] == 42


@pytest.mark.usefixtures("qgis_plugin_path")
class TestList:
    @pytest.mark.parametrize(
        "module, alg_name, api_name, fn, output",
        [
            ("vector.list", "ListVectorsAlgorithm", "vector", "get_vectors", "VECTORS"),
            ("raster.list", "ListRastersAlgorithm", "raster", "get_rasters", "RASTERS"),
        ],
    )
    def test_lists_given_project(
        self, api, monkeypatch, module, alg_name, api_name, fn, output
    ):
        requested = []
        monkeypatch.setattr(
            getattr(api, api_name),
            fn,
            lambda i: requested.append(i) or [{"id": "x", "project": {"id": i}}],
        )

        result = _run(_alg(module, alg_name), {"PROJECT_ID": "p9"})

        assert requested == ["p9"]
        assert result[output] == [{"id": "x"}]


@pytest.mark.usefixtures("qgis_plugin_path")
class TestVector:
    def _update_alg(self):
        return _alg("vector.update", "UpdateVectorAlgorithm")

    def test_update_sends_only_given_fields(self, api, monkeypatch):
        captured = {}

        def fake(vector_id, **changes):
            captured["id"] = vector_id
            captured["changes"] = changes
            return {"id": vector_id}

        monkeypatch.setattr(api.vector, "update_vector", fake)

        _run(self._update_alg(), {"VECTOR_ID": "v1", "NAME": "new"})

        assert captured == {"id": "v1", "changes": {"name": "new"}}

    def test_update_without_changes_fails(self):
        with pytest.raises(QgsProcessingException, match="Nothing to update"):
            _run(self._update_alg(), {"VECTOR_ID": "v1"})

    def test_update_rejects_too_long_name(self):
        with pytest.raises(QgsProcessingException, match="32 characters"):
            _run(self._update_alg(), {"VECTOR_ID": "v1", "NAME": "x" * 33})

    def test_update_shows_max_length_in_label(self):
        alg = self._update_alg()
        alg.initAlgorithm()
        assert "32" in alg.parameterDefinition("NAME").description()
        assert "255" in alg.parameterDefinition("ATTRIBUTION").description()

    def test_delete_clears_local_cache(self, api, local_cache, monkeypatch):
        calls = []
        monkeypatch.setattr(
            api.vector, "delete_vector", lambda i: calls.append(("api", i))
        )
        monkeypatch.setattr(
            local_cache.vector, "clear", lambda i: calls.append(("cache", i)) or True
        )

        result = _run(
            _alg("vector.delete", "DeleteVectorAlgorithm"), {"VECTOR_ID": "v1"}
        )

        assert calls == [("api", "v1"), ("cache", "v1")]
        assert result["VECTOR_ID"] == "v1"

    def test_add_to_map_loads_layer_on_completion(self, api, monkeypatch):
        from plugin_dir.kumoy import vector_layer

        monkeypatch.setattr(
            api.vector,
            "get_vector",
            lambda _: SimpleNamespace(projectId="p1", name="Roads"),
        )
        # The real provider needs the Kumoy server, so stand in a memory layer
        layer = QgsVectorLayer("LineString?crs=EPSG:4326", "tmp", "memory")
        monkeypatch.setattr(vector_layer, "create_vector_layer", lambda _: layer)

        alg = _alg("vector.add_to_map", "AddVectorToMapAlgorithm")
        alg.initAlgorithm()
        context = QgsProcessingContext()
        result = alg.processAlgorithm(
            {"VECTOR_ID": "v1"}, context, QgsProcessingFeedback()
        )

        assert result["OUTPUT"] == layer.id()
        assert context.temporaryLayerStore().mapLayer(layer.id()) is layer
        details = context.layersToLoadOnCompletion()[layer.id()]
        assert details.name == "Roads"
        assert details.outputName == "OUTPUT"

    def test_blank_id_fails(self):
        with pytest.raises(QgsProcessingException, match="required"):
            _run(_alg("vector.get", "GetVectorAlgorithm"), {"VECTOR_ID": "  "})


@pytest.mark.usefixtures("qgis_plugin_path")
class TestRaster:
    def test_add_to_map_loads_layer_on_completion(self, api, monkeypatch, tmp_path):
        from plugin_dir.kumoy import raster_layer

        monkeypatch.setattr(
            api.raster,
            "get_raster",
            lambda _: SimpleNamespace(projectId="p1", name="DEM"),
        )
        # The real provider needs the Kumoy server, so stand in an empty layer
        layer = QgsRasterLayer(str(tmp_path / "tmp.tif"), "tmp")
        monkeypatch.setattr(raster_layer, "create_raster_layer", lambda _: layer)

        alg = _alg("raster.add_to_map", "AddRasterToMapAlgorithm")
        alg.initAlgorithm()
        context = QgsProcessingContext()
        result = alg.processAlgorithm(
            {"RASTER_ID": "r1"}, context, QgsProcessingFeedback()
        )

        assert result["OUTPUT"] == layer.id()
        details = context.layersToLoadOnCompletion()[layer.id()]
        assert details.name == "DEM"
        assert details.outputName == "OUTPUT"

    def test_update_sends_only_given_fields(self, api, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            api.raster,
            "update_raster",
            lambda raster_id, **changes: captured.update(changes) or {},
        )

        _run(
            _alg("raster.update", "UpdateRasterAlgorithm"),
            {"RASTER_ID": "r1", "ATTRIBUTION": "(c) me"},
        )

        assert captured == {"attribution": "(c) me"}


@pytest.mark.usefixtures("qgis_plugin_path")
class TestMainThread:
    @pytest.mark.parametrize(
        "module, alg_name, expected",
        [
            ("vector.add_to_map", "AddVectorToMapAlgorithm", True),
            ("raster.add_to_map", "AddRasterToMapAlgorithm", True),
            ("vector.update", "UpdateVectorAlgorithm", False),
            ("vector.upload.algorithm", "UploadVectorAlgorithm", False),
            ("raster.upload.algorithm", "UploadRasterAlgorithm", False),
        ],
    )
    def test_flag_and_help_match(self, module, alg_name, expected):
        alg = _alg(module, alg_name)

        no_threading = bool(alg.flags() & Qgis.ProcessingAlgorithmFlag.NoThreading)
        assert no_threading is expected
        # Script authors calling processing.run() are not covered by the flag
        assert ("main thread" in alg.shortHelpString()) is expected


@pytest.mark.usefixtures("qgis_plugin_path")
class TestApiErrors:
    def _raise(self, error):
        def fake(*_, **__):
            raise error

        return fake

    @pytest.fixture
    def handled(self, base, monkeypatch):
        handled = []
        monkeypatch.setattr(base, "handle_api_error", handled.append)
        return handled

    def test_unauthorized_ends_session_only_in_gui(
        self, api, base, handled, monkeypatch
    ):
        error = api.error.UnauthorizedError("Unauthorized", "expired")
        monkeypatch.setattr(api.raster, "get_raster", self._raise(error))
        alg = _alg("raster.get", "GetRasterAlgorithm")

        # Headless (qgis_process) or layer conversion: no project in the context
        with pytest.raises(QgsProcessingException, match="expired"):
            _run(alg, {"RASTER_ID": "r1"})
        assert handled == []

        monkeypatch.setattr(base, "iface", object())
        gui_context = QgsProcessingContext()
        gui_context.setProject(QgsProject.instance())
        with pytest.raises(QgsProcessingException, match="(?i)log in"):
            _run(
                _alg("raster.get", "GetRasterAlgorithm"),
                {"RASTER_ID": "r1"},
                gui_context,
            )
        assert handled == [error]

    @pytest.mark.parametrize(
        "error_name, message",
        [
            ("ForbiddenError", "permission"),
            ("QuotaExceededError", "limit"),
            ("NotFoundError", "Not Found - raster"),
        ],
    )
    def test_errors_become_processing_exceptions(
        self, api, handled, monkeypatch, error_name, message
    ):
        error = getattr(api.error, error_name)("Not Found", "raster")
        monkeypatch.setattr(api.raster, "get_raster", self._raise(error))

        with pytest.raises(QgsProcessingException, match=message):
            _run(_alg("raster.get", "GetRasterAlgorithm"), {"RASTER_ID": "r1"})
        # Only 401 ends the session
        assert handled == []


@pytest.mark.usefixtures("qgis_plugin_path")
class TestBrowserRefresh:
    @pytest.fixture
    def refreshed(self, base, monkeypatch):
        calls = []
        monkeypatch.setattr(base, "run_on_main_thread", calls.append)
        monkeypatch.setattr(base, "iface", object())
        return calls

    def _gui_context(self):
        context = QgsProcessingContext()
        context.setProject(QgsProject.instance())
        return context

    def test_change_in_gui_refreshes_browser(
        self, api, base, local_cache, refreshed, monkeypatch
    ):
        monkeypatch.setattr(api.vector, "delete_vector", lambda _: None)
        monkeypatch.setattr(local_cache.vector, "clear", lambda _: True)

        _run(
            _alg("vector.delete", "DeleteVectorAlgorithm"),
            {"VECTOR_ID": "v1"},
            self._gui_context(),
        )

        assert refreshed == [base.refresh_kumoy_browser]

    def test_read_only_tool_does_not_refresh(self, api, refreshed, monkeypatch):
        monkeypatch.setattr(api.vector, "get_vectors", lambda _: [])

        _run(
            _alg("vector.list", "ListVectorsAlgorithm"),
            {"PROJECT_ID": "p1"},
            self._gui_context(),
        )

        assert refreshed == []

    def test_projectless_context_does_not_refresh(
        self, api, local_cache, refreshed, monkeypatch
    ):
        # Layer conversion runs the upload tools while holding Browser items
        monkeypatch.setattr(api.vector, "delete_vector", lambda _: None)
        monkeypatch.setattr(local_cache.vector, "clear", lambda _: True)

        _run(_alg("vector.delete", "DeleteVectorAlgorithm"), {"VECTOR_ID": "v1"})

        assert refreshed == []


@pytest.mark.usefixtures("qgis_plugin_path")
class TestUploadProjectChoices:
    @pytest.fixture(params=["vector", "raster"])
    def alg_class(self, request, base, monkeypatch):
        monkeypatch.setattr(
            base, "_project_choices", [("p1", "Org / A"), ("p2", "Org / B")]
        )
        module = importlib.import_module(
            f"plugin_dir.processing.{request.param}.upload.algorithm"
        )
        return getattr(module, f"Upload{request.param.capitalize()}Algorithm")

    def test_project_id_overrides_enum(self, alg_class):
        alg = alg_class()
        alg.initAlgorithm()
        project_id = alg._resolve_project_id(
            {"PROJECT_ID": " p9 ", "PROJECT": 1}, QgsProcessingContext()
        )
        assert project_id == "p9"

    def test_falls_back_to_enum(self, alg_class):
        alg = alg_class()
        alg.initAlgorithm()
        assert alg._resolve_project_id({"PROJECT": 1}, QgsProcessingContext()) == "p2"

    def test_enum_labels_and_selected_default(self, alg_class, monkeypatch):
        _select_project(monkeypatch, "p2")
        alg = alg_class()
        alg.initAlgorithm()

        definition = alg.parameterDefinition("PROJECT")
        assert definition.options() == ["Org / A", "Org / B"]
        assert definition.defaultValue() == 1

    def test_run_copy_keeps_the_list_the_dialog_showed(
        self, alg_class, base, monkeypatch
    ):
        dialog_alg = alg_class()
        dialog_alg.initAlgorithm()
        # A background refresh lands while the dialog is open
        monkeypatch.setattr(
            base,
            "_project_choices",
            [("p0", "Org / New"), ("p1", "Org / A"), ("p2", "Org / B")],
        )

        # The toolbox runs a create()d copy
        run_alg = dialog_alg.create()

        assert (
            run_alg._resolve_project_id({"PROJECT": 1}, QgsProcessingContext()) == "p2"
        )

    def test_prototype_does_not_pin_its_list(self, alg_class, base, monkeypatch):
        prototype = alg_class(prototype=True)
        prototype.initAlgorithm()
        monkeypatch.setattr(base, "_project_choices", [("p3", "Org / C")])

        alg = prototype.create()

        assert alg.parameterDefinition("PROJECT").options() == ["Org / C"]

    def test_empty_list_still_accepts_project_id(self, alg_class, base, monkeypatch):
        monkeypatch.setattr(base, "_project_choices", [])
        alg = alg_class()
        alg.initAlgorithm()

        # A required enum without options would reject runs that pass PROJECT_ID
        flags = alg.parameterDefinition("PROJECT").flags()
        assert flags & Qgis.ProcessingParameterFlag.Optional
        with pytest.raises(QgsProcessingException, match="open it again"):
            alg._resolve_project_id({}, QgsProcessingContext())

    def test_init_does_not_call_the_network(self, alg_class, api, monkeypatch):
        def fail(*_):
            raise AssertionError("network in initAlgorithm")

        monkeypatch.setattr(api.organization, "get_organizations", fail)
        monkeypatch.setattr(api.organization, "get_projects", fail)

        alg_class().initAlgorithm()


@pytest.mark.usefixtures("qgis_plugin_path")
class TestRefreshProjectChoices:
    @pytest.fixture
    def tasks(self, base, monkeypatch):
        from ._real_tasks import RealTasks

        tasks = RealTasks()
        monkeypatch.setattr(base, "run_task", tasks.run_task)
        return tasks

    def test_lists_writable_projects(self, api, base, tasks, monkeypatch):
        monkeypatch.setattr(
            api.organization,
            "get_organizations",
            lambda: [
                SimpleNamespace(id="o1", name="Org", scheduledDeletionAt=None),
                SimpleNamespace(id="o2", name="Gone", scheduledDeletionAt="2026-01-01"),
            ],
        )
        monkeypatch.setattr(
            api.organization,
            "get_my_teams",
            lambda _: [
                SimpleNamespace(id="t1", role="ADMIN"),
                SimpleNamespace(id="t2", role="MEMBER"),
            ],
        )
        monkeypatch.setattr(
            api.organization,
            "get_projects",
            lambda _: [
                SimpleNamespace(id="p1", name="A", teamId="t1"),
                SimpleNamespace(id="p2", name="B", teamId="t2"),
            ],
        )

        base.refresh_project_choices()
        assert len(tasks.queue) == 1
        tasks.flush()

        assert base.project_choices() == [("p1", "Org / A")]
        # Throttled: a second call right away does not fetch again
        base.refresh_project_choices()
        assert tasks.queue == []

    def test_logout_clears(self, base, tasks, monkeypatch):
        from plugin_dir.kumoy import session

        monkeypatch.setattr(base, "_project_choices", [("p1", "Org / A")])
        monkeypatch.setattr(session, "_token", None)

        base.refresh_project_choices()

        assert base.project_choices() == []
        assert tasks.queue == []

    def test_fetch_for_a_previous_login_is_dropped(self, api, base, monkeypatch):
        """Real QgsTask: log out and back in while the first fetch runs."""
        import threading
        import time

        from qgis.PyQt.QtCore import QCoreApplication

        from plugin_dir.kumoy import session, tasks

        monkeypatch.setattr(base, "run_task", tasks.run_task)  # the real one
        monkeypatch.setattr(session, "_token", "first-user")
        monkeypatch.setattr(base, "_project_choices", [])
        monkeypatch.setattr(base, "_refreshing", False)
        monkeypatch.setattr(base, "_last_refresh", 0.0)
        release = threading.Event()
        finished = []

        def get_organizations():
            release.wait(10)
            finished.append(1)
            return [SimpleNamespace(id="o1", name="Old", scheduledDeletionAt=None)]

        monkeypatch.setattr(api.organization, "get_organizations", get_organizations)
        monkeypatch.setattr(
            api.organization,
            "get_my_teams",
            lambda _: [SimpleNamespace(id="t1", role="ADMIN")],
        )
        monkeypatch.setattr(
            api.organization,
            "get_projects",
            lambda _: [SimpleNamespace(id="p-old", name="A", teamId="t1")],
        )

        base.refresh_project_choices()
        base.forget_project_choices()  # login changed while it runs
        monkeypatch.setattr(session, "_token", "second-user")
        release.set()

        deadline = time.monotonic() + 10
        while not finished:
            assert time.monotonic() < deadline
            QCoreApplication.processEvents()
            time.sleep(0.01)
        for _ in range(50):  # let the task's finished() callback run
            QCoreApplication.processEvents()
            time.sleep(0.01)
        assert base.project_choices() == []


@pytest.mark.usefixtures("qgis_plugin_path")
class TestSelectedProject:
    """Resource IDs work across projects, except adding to the map: a map must
    not mix layers of different projects."""

    def test_no_selected_project_fails(self, monkeypatch):
        _select_project(monkeypatch, "")

        with pytest.raises(QgsProcessingException, match="No Kumoy project"):
            _run(_alg("organization.get_project", "GetProjectAlgorithm"), {})

    @pytest.mark.parametrize(
        "module, api_name, alg_name, getter, parameters",
        [
            (
                "vector.add_to_map",
                "vector",
                "AddVectorToMapAlgorithm",
                "get_vector",
                {"VECTOR_ID": "v1"},
            ),
            (
                "raster.add_to_map",
                "raster",
                "AddRasterToMapAlgorithm",
                "get_raster",
                {"RASTER_ID": "r1"},
            ),
        ],
    )
    def test_add_to_map_of_other_project_fails(
        self, api, monkeypatch, module, api_name, alg_name, getter, parameters
    ):
        monkeypatch.setattr(
            getattr(api, api_name), getter, lambda _: SimpleNamespace(projectId="p2")
        )

        with pytest.raises(QgsProcessingException, match="selected Kumoy project"):
            _run(_alg(module, alg_name), parameters)

    @pytest.mark.parametrize(
        "module, api_name, alg_name, mutator, parameters",
        [
            (
                "vector.update",
                "vector",
                "UpdateVectorAlgorithm",
                "update_vector",
                {"VECTOR_ID": "v1", "NAME": "n"},
            ),
            (
                "vector.delete",
                "vector",
                "DeleteVectorAlgorithm",
                "delete_vector",
                {"VECTOR_ID": "v1"},
            ),
            (
                "raster.update",
                "raster",
                "UpdateRasterAlgorithm",
                "update_raster",
                {"RASTER_ID": "r1", "NAME": "n"},
            ),
            (
                "raster.delete",
                "raster",
                "DeleteRasterAlgorithm",
                "delete_raster",
                {"RASTER_ID": "r1"},
            ),
        ],
    )
    def test_resource_id_works_without_selected_project(
        self,
        api,
        local_cache,
        monkeypatch,
        module,
        api_name,
        alg_name,
        mutator,
        parameters,
    ):
        _select_project(monkeypatch, "")
        called = []
        monkeypatch.setattr(
            getattr(api, api_name), mutator, lambda *a, **k: called.append(a) or {}
        )
        for cache in (local_cache.vector, local_cache.raster):
            monkeypatch.setattr(cache, "clear", lambda _: True)

        _run(_alg(module, alg_name), parameters)

        assert len(called) == 1


@pytest.mark.usefixtures("qgis_plugin_path")
class TestNotLoggedIn:
    @pytest.fixture(autouse=True)
    def logged_out(self, monkeypatch):
        from plugin_dir.kumoy import session

        monkeypatch.setattr(session, "_token", None)
        # Logging out also clears the selected project
        _select_project(monkeypatch, "")

    @pytest.mark.parametrize(
        "module, alg_name, parameters",
        [
            ("organization.list_organizations", "ListOrganizationsAlgorithm", {}),
            ("organization.get_project", "GetProjectAlgorithm", {}),
            ("vector.get", "GetVectorAlgorithm", {"VECTOR_ID": "v1"}),
            ("vector.upload.algorithm", "UploadVectorAlgorithm", {"PROJECT_ID": "p1"}),
            ("raster.upload.algorithm", "UploadRasterAlgorithm", {"PROJECT_ID": "p1"}),
        ],
    )
    def test_says_not_logged_in(self, module, alg_name, parameters):
        with pytest.raises(QgsProcessingException, match="not logged in"):
            _run(_alg(module, alg_name), parameters)


@pytest.mark.usefixtures("qgis_plugin_path")
class TestServerUrlInLoginErrors:
    @pytest.fixture(autouse=True)
    def custom_server(self, api, monkeypatch):
        monkeypatch.setattr(
            api.config,
            "get_api_config",
            lambda: api.config.ApiConfig(SERVER_URL="https://kumoy.example.com"),
        )

    def test_not_logged_in(self, monkeypatch):
        from plugin_dir.kumoy import session

        monkeypatch.setattr(session, "_token", None)

        with pytest.raises(QgsProcessingException, match="https://kumoy.example.com"):
            _run(
                _alg("organization.list_organizations", "ListOrganizationsAlgorithm"),
                {},
            )

    def test_rejected(self, api, monkeypatch):
        def fake():
            raise api.error.UnauthorizedError("Unauthorized", "expired")

        monkeypatch.setattr(api.organization, "get_organizations", fake)

        with pytest.raises(QgsProcessingException, match="https://kumoy.example.com"):
            _run(
                _alg("organization.list_organizations", "ListOrganizationsAlgorithm"),
                {},
            )


@pytest.mark.usefixtures("qgis_plugin_path")
def test_provider_loads_all_tools():
    from plugin_dir.processing.provider import KumoyProcessingProvider

    provider = KumoyProcessingProvider()
    provider.refreshAlgorithms()

    ids = {alg.name() for alg in provider.algorithms()}
    assert {
        "uploadvector",
        "uploadraster",
        "listorganizations",
        "listprojects",
        "getproject",
        "listvectors",
        "getvector",
        "addvectortomap",
        "updatevector",
        "deletevector",
        "listrasters",
        "getraster",
        "addrastertomap",
        "updateraster",
        "deleteraster",
    } <= ids


@pytest.mark.usefixtures("qgis_plugin_path")
class TestUploadRasterFlow:
    """The contract _upload_raster relies on: RASTER_ID, {} on cancel, cleanup."""

    @pytest.fixture
    def flow(self, api, local_cache, monkeypatch, tmp_path):
        from osgeo import gdal, osr

        from qgis.PyQt import sip

        from plugin_dir.processing.raster.upload import algorithm

        path = str(tmp_path / "src.tif")
        ds = gdal.GetDriverByName("GTiff").Create(path, 4, 4, 1, gdal.GDT_Byte)
        ds.SetGeoTransform([0, 1, 0, 4, 0, -1])
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        ds.SetProjection(srs.ExportToWkt())
        ds.FlushCache()
        ds.Close()
        calls = []
        organization = SimpleNamespace(
            usage=SimpleNamespace(vectors=0, rasters=0, usedStorageUnits=0),
            availableStorageUnits=10,
            planSettings=SimpleNamespace(maxRasters=10),
        )
        project = SimpleNamespace(
            role="ADMIN", team=SimpleNamespace(organizationId="o1")
        )
        monkeypatch.setattr(api.project, "get_project", lambda _: project)
        monkeypatch.setattr(
            api.organization, "get_organization", lambda _: organization
        )

        def convert_to_cog(src_path, dst_path, **_):
            with open(dst_path, "wb") as f:
                f.write(b"cog")

        def create_raster(*args):
            calls.append(("create",) + args)
            return SimpleNamespace(raster_id="r1", upload_url="https://s3")

        monkeypatch.setattr(algorithm, "convert_to_cog", convert_to_cog)
        monkeypatch.setattr(api.raster, "create_raster", create_raster)
        monkeypatch.setattr(
            api.raster, "delete_raster", lambda i: calls.append(("delete", i))
        )
        monkeypatch.setattr(
            local_cache.raster, "store", lambda i, p: calls.append(("store", i))
        )
        layer = QgsRasterLayer(path, "dem", "gdal")
        assert layer.isValid()
        yield SimpleNamespace(algorithm=algorithm, layer=layer, calls=calls)
        # Not left to the garbage collector after QGIS has exited
        sip.delete(layer)

    def _run(self, flow):
        alg = flow.algorithm.UploadRasterAlgorithm()
        alg.initAlgorithm()
        return alg.processAlgorithm(
            {"INPUT": flow.layer, "PROJECT_ID": "p1"},
            QgsProcessingContext(),
            QgsProcessingFeedback(),
        )

    def test_success_caches_the_cog(self, flow, monkeypatch):
        monkeypatch.setattr(
            flow.algorithm, "upload_file_to_presigned_put", lambda **_: None
        )

        assert self._run(flow) == {"RASTER_ID": "r1"}
        assert flow.calls == [("create", "p1", "dem", 3), ("store", "r1")]

    def test_cancel_during_upload_cleans_up(self, flow, monkeypatch):
        def cancel(**_):
            raise flow.algorithm.UploadCanceled()

        monkeypatch.setattr(flow.algorithm, "upload_file_to_presigned_put", cancel)

        assert self._run(flow) == {}
        assert flow.calls[-1] == ("delete", "r1")

    def test_failure_cleans_up_and_explains(self, flow, api, monkeypatch):
        def fail(**_):
            raise api.error.NetworkError("offline")

        monkeypatch.setattr(flow.algorithm, "upload_file_to_presigned_put", fail)

        with pytest.raises(QgsProcessingException, match="Could not connect"):
            self._run(flow)
        assert flow.calls[-1] == ("delete", "r1")
