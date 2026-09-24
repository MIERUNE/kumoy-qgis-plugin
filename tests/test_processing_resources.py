"""Kumoy リソースを操作する Processing アルゴリズムのテスト（API 関数をモックする）"""

import zipfile
from types import SimpleNamespace

import pytest
from qgis.core import (
    Qgis,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsRasterLayer,
    QgsVectorLayer,
)


def _run(alg, parameters):
    """Run like processing.run() does, but in-process so monkeypatches apply."""
    alg.initAlgorithm()
    return alg.processAlgorithm(
        parameters, QgsProcessingContext(), QgsProcessingFeedback()
    )


@pytest.fixture
def api(qgis_plugin_path):
    from plugin_dir.kumoy import api

    return api


@pytest.fixture
def local_cache(qgis_plugin_path):
    from plugin_dir.kumoy import local_cache

    return local_cache


def _select_project(monkeypatch, project_id):
    from plugin_dir.processing import base

    monkeypatch.setattr(
        base,
        "get_settings",
        lambda: SimpleNamespace(selected_project_id=project_id),
    )


@pytest.fixture(autouse=True)
def selected_project(qgis_plugin_path, api, monkeypatch):
    """Select p1 and make every vector/raster/map belong to it unless overridden."""
    _select_project(monkeypatch, "p1")
    in_p1 = lambda _: SimpleNamespace(projectId="p1")  # noqa: E731
    monkeypatch.setattr(api.vector, "get_vector", in_p1)
    monkeypatch.setattr(api.raster, "get_raster", in_p1)
    monkeypatch.setattr(api.styledmap, "get_styled_map", in_p1)


@pytest.mark.usefixtures("qgis_plugin_path")
class TestProject:
    def test_list_organizations_returns_plain_dicts(self, api, monkeypatch):
        from plugin_dir.processing.organization.list_organizations import (
            ListOrganizationsAlgorithm,
        )

        org = api.organization.OrganizationWithRole(
            id="o1",
            name="Org",
            stripeCustomerId=None,
            subscriptionPlan="FREE",
            storageUnits=1,
            createdAt="",
            updatedAt="",
            role="OWNER",
            scheduledDeletionAt=None,
        )
        monkeypatch.setattr(api.organization, "get_organizations", lambda: [org])

        result = _run(ListOrganizationsAlgorithm(), {})

        assert result["ORGANIZATIONS"] == [
            {
                "id": "o1",
                "name": "Org",
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
        from plugin_dir.processing.organization.list_projects import (
            ListProjectsAlgorithm,
        )

        captured = {}

        def fake(organization_id):
            captured["id"] = organization_id
            return []

        monkeypatch.setattr(api.project, "get_projects_by_organization", fake)

        result = _run(ListProjectsAlgorithm(), {"ORGANIZATION_ID": " o1 "})

        assert captured["id"] == "o1"
        assert result["PROJECTS"] == []

    def test_result_is_written_to_html_for_results_viewer(self, api, monkeypatch):
        from plugin_dir.processing.organization.list_projects import (
            ListProjectsAlgorithm,
        )

        monkeypatch.setattr(
            api.project, "get_projects_by_organization", lambda _: [{"name": "<P>"}]
        )

        result = _run(ListProjectsAlgorithm(), {"ORGANIZATION_ID": "o1"})

        with open(result["HTML"], encoding="utf-8") as f:
            assert "&lt;P&gt;" in f.read()

    def test_get_project_targets_selected_project(self, api, monkeypatch):
        from plugin_dir.processing.organization.get_project import GetProjectAlgorithm

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

        result = _run(GetProjectAlgorithm(), {})

        assert requested == ["p1"]
        assert result["PROJECT"] == {
            "id": "p1",
            "name": "P",
            "vectors": [{"id": "v1"}],
            "rasters": [{"id": "r1"}],
            "maps": [{"id": "m1"}],
        }


@pytest.mark.usefixtures("qgis_plugin_path")
class TestVector:
    def _update_alg(self):
        from plugin_dir.processing.vector.update import UpdateVectorAlgorithm

        return UpdateVectorAlgorithm()

    def test_update_sends_only_given_fields(self, api, monkeypatch):
        captured = {}

        def fake(vector_id, options):
            captured["id"] = vector_id
            captured["options"] = options
            return {"id": vector_id}

        monkeypatch.setattr(api.vector, "update_vector", fake)

        _run(self._update_alg(), {"VECTOR_ID": "v1", "NAME": "new"})

        assert captured["id"] == "v1"
        assert captured["options"] == api.vector.UpdateVectorOptions(name="new")

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
        from plugin_dir.processing.vector.delete import DeleteVectorAlgorithm

        calls = []
        monkeypatch.setattr(
            api.vector, "delete_vector", lambda i: calls.append(("api", i))
        )
        monkeypatch.setattr(
            local_cache.vector, "clear", lambda i: calls.append(("cache", i)) or True
        )

        result = _run(DeleteVectorAlgorithm(), {"VECTOR_ID": "v1"})

        assert calls == [("api", "v1"), ("cache", "v1")]
        assert result["VECTOR_ID"] == "v1"

    def test_add_to_map_loads_layer_on_completion(self, api, monkeypatch):
        from plugin_dir.kumoy import vector_layer
        from plugin_dir.processing.vector.add_to_map import AddVectorToMapAlgorithm

        monkeypatch.setattr(
            api.vector,
            "get_vector",
            lambda _: SimpleNamespace(projectId="p1", name="Roads"),
        )
        # The real provider needs the Kumoy server, so stand in a memory layer
        layer = QgsVectorLayer("LineString?crs=EPSG:4326", "tmp", "memory")
        monkeypatch.setattr(vector_layer, "create_vector_layer", lambda _: layer)

        alg = AddVectorToMapAlgorithm()
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

    def test_add_to_map_runs_on_main_thread(self):
        from plugin_dir.processing.vector.add_to_map import AddVectorToMapAlgorithm

        assert (
            AddVectorToMapAlgorithm().flags() & Qgis.ProcessingAlgorithmFlag.NoThreading
        )

    def test_blank_id_fails(self):
        from plugin_dir.processing.vector.get import GetVectorAlgorithm

        with pytest.raises(QgsProcessingException, match="required"):
            _run(GetVectorAlgorithm(), {"VECTOR_ID": "  "})


@pytest.mark.usefixtures("qgis_plugin_path")
class TestRaster:
    def test_add_to_map_loads_layer_on_completion(self, api, monkeypatch, tmp_path):
        from plugin_dir.kumoy import raster_layer
        from plugin_dir.processing.raster.add_to_map import AddRasterToMapAlgorithm

        monkeypatch.setattr(
            api.raster,
            "get_raster",
            lambda _: SimpleNamespace(projectId="p1", name="DEM"),
        )
        # The real provider needs the Kumoy server, so stand in an empty layer
        layer = QgsRasterLayer(str(tmp_path / "tmp.tif"), "tmp")
        monkeypatch.setattr(raster_layer, "create_raster_layer", lambda _: layer)

        alg = AddRasterToMapAlgorithm()
        alg.initAlgorithm()
        context = QgsProcessingContext()
        result = alg.processAlgorithm(
            {"RASTER_ID": "r1"}, context, QgsProcessingFeedback()
        )

        assert result["OUTPUT"] == layer.id()
        assert context.temporaryLayerStore().mapLayer(layer.id()) is layer
        details = context.layersToLoadOnCompletion()[layer.id()]
        assert details.name == "DEM"
        assert details.outputName == "OUTPUT"

    def test_add_to_map_runs_on_main_thread(self):
        from plugin_dir.processing.raster.add_to_map import AddRasterToMapAlgorithm

        assert (
            AddRasterToMapAlgorithm().flags() & Qgis.ProcessingAlgorithmFlag.NoThreading
        )


@pytest.mark.usefixtures("qgis_plugin_path")
class TestApiErrors:
    def _raise(self, error):
        def fake(*_):
            raise error

        return fake

    def test_unauthorized_becomes_processing_exception(self, api, monkeypatch):
        from plugin_dir.processing.raster.get import GetRasterAlgorithm

        monkeypatch.setattr(
            api.raster,
            "get_raster",
            self._raise(api.error.UnauthorizedError("Unauthorized", "expired")),
        )

        with pytest.raises(QgsProcessingException, match="expired"):
            _run(GetRasterAlgorithm(), {"RASTER_ID": "r1"})

    def test_not_found_becomes_processing_exception(self, api, monkeypatch):
        from plugin_dir.processing.raster.get import GetRasterAlgorithm

        monkeypatch.setattr(
            api.raster,
            "get_raster",
            self._raise(api.error.NotFoundError("Not Found", "raster")),
        )

        with pytest.raises(QgsProcessingException, match="Not Found - raster"):
            _run(GetRasterAlgorithm(), {"RASTER_ID": "r1"})


@pytest.mark.usefixtures("qgis_plugin_path")
class TestMap:
    def _capture_update(self, api, monkeypatch):
        captured = {}

        def fake(map_id, options):
            captured["options"] = options
            return {"id": map_id, "qgisproject": "<qgis/>"}

        monkeypatch.setattr(api.styledmap, "update_styled_map", fake)
        return captured

    def _update_alg(self):
        from plugin_dir.processing.map.update import UpdateMapAlgorithm

        return UpdateMapAlgorithm()

    def test_create_without_file_uploads_empty_project(self, api, monkeypatch):
        from plugin_dir.processing.map.create import CreateMapAlgorithm

        captured = {}

        def fake(project_id, options):
            captured["project_id"] = project_id
            captured["options"] = options
            return {"id": "m1", "qgisproject": options.qgisproject}

        monkeypatch.setattr(api.styledmap, "add_styled_map", fake)

        result = _run(
            CreateMapAlgorithm(),
            {"NAME": "map", "IS_PUBLIC": True},
        )

        assert captured["project_id"] == "p1"
        assert "<qgis" in captured["options"].qgisproject
        assert captured["options"].isPublic is True
        assert captured["options"].description is None
        # The project XML is too large to return as a result
        assert result["MAP"] == {"id": "m1"}

    def test_create_requires_name(self):
        from plugin_dir.processing.map.create import CreateMapAlgorithm

        with pytest.raises(QgsProcessingException, match="required"):
            _run(CreateMapAlgorithm(), {"NAME": ""})

    @pytest.fixture
    def uploads(self, monkeypatch, tmp_path):
        from plugin_dir.kumoy.local_cache import map as map_cache
        from plugin_dir.processing.map import create, update

        cache_dir = tmp_path / "maps"
        cache_dir.mkdir()
        monkeypatch.setattr(map_cache, "get_cache_dir", lambda: str(cache_dir))
        uploads = []
        for module in (create, update):
            monkeypatch.setattr(
                module,
                "upload_sprites",
                lambda map_id, sprite: uploads.append((map_id, sprite.assets_hash)),
            )
        return uploads

    def _current_map(self, api, monkeypatch, assets_hash):
        monkeypatch.setattr(
            api.styledmap,
            "get_styled_map",
            lambda _: SimpleNamespace(projectId="p1", assetsHash=assets_hash),
        )

    def test_update_reads_project_from_qgz(self, api, monkeypatch, tmp_path, uploads):
        from .project_files import to_qgz, write_kumoy_point_project

        captured = self._capture_update(api, monkeypatch)
        self._current_map(api, monkeypatch, None)
        qgz = to_qgz(write_kumoy_point_project(tmp_path))

        _run(self._update_alg(), {"MAP_ID": "m1", "PROJECT_FILE": str(qgz)})

        assert "vector_id=v1" in captured["options"].qgisproject
        assert captured["options"].isPublic is None

    def test_update_uploads_sprites_of_project_file(
        self, api, monkeypatch, tmp_path, uploads
    ):
        from .project_files import fixed_aspect_ratios, write_kumoy_point_project

        captured = self._capture_update(api, monkeypatch)
        self._current_map(api, monkeypatch, "old")
        path = write_kumoy_point_project(tmp_path)

        _run(self._update_alg(), {"MAP_ID": "m1", "PROJECT_FILE": str(path)})

        new_hash = captured["options"].assetsHash
        assert new_hash not in (None, "old")
        assert uploads == [("m1", new_hash)]
        assert fixed_aspect_ratios(captured["options"].qgisproject) == ["0.5"]

    def test_update_skips_unchanged_sprites(self, api, monkeypatch, tmp_path, uploads):
        from plugin_dir.kumoy.sprite import generate_sprite
        from plugin_dir.kumoy.local_cache import map as map_cache
        from .project_files import write_kumoy_point_project

        path = write_kumoy_point_project(tmp_path)
        assets_hash = generate_sprite(
            map_cache.read_project_file(str(path))
        ).assets_hash
        captured = self._capture_update(api, monkeypatch)
        self._current_map(api, monkeypatch, assets_hash)

        _run(self._update_alg(), {"MAP_ID": "m1", "PROJECT_FILE": str(path)})

        assert uploads == []
        assert captured["options"].assetsHash is api.styledmap._UNSET

    def test_update_clears_sprites_without_point_symbols(
        self, api, monkeypatch, tmp_path, uploads
    ):
        from qgis.core import QgsProject

        captured = self._capture_update(api, monkeypatch)
        self._current_map(api, monkeypatch, "old")
        path = str(tmp_path / "empty.qgs")
        QgsProject().write(path)

        _run(self._update_alg(), {"MAP_ID": "m1", "PROJECT_FILE": path})

        assert uploads == []
        assert captured["options"].assetsHash is None

    def test_create_uploads_sprites_of_project_file(
        self, api, monkeypatch, tmp_path, uploads
    ):
        from plugin_dir.processing.map.create import CreateMapAlgorithm
        from .project_files import write_kumoy_point_project

        monkeypatch.setattr(
            api.styledmap, "add_styled_map", lambda *_: SimpleNamespace(id="m1")
        )
        captured = self._capture_update(api, monkeypatch)
        path = write_kumoy_point_project(tmp_path)

        _run(CreateMapAlgorithm(), {"NAME": "map", "PROJECT_FILE": str(path)})

        new_hash = captured["options"].assetsHash
        assert new_hash is not None
        assert uploads == [("m1", new_hash)]

    @pytest.mark.parametrize("index, expected", [(1, True), (2, False)])
    def test_update_visibility(self, api, monkeypatch, index, expected):
        captured = self._capture_update(api, monkeypatch)

        _run(self._update_alg(), {"MAP_ID": "m1", "IS_PUBLIC": index})

        assert captured["options"].isPublic is expected

    def test_update_without_changes_fails(self):
        with pytest.raises(QgsProcessingException, match="Nothing to update"):
            _run(self._update_alg(), {"MAP_ID": "m1"})

    def test_get_writes_project_file(self, api, monkeypatch, tmp_path):
        from plugin_dir.processing.map.get import GetMapAlgorithm

        monkeypatch.setattr(
            api.styledmap,
            "get_styled_map",
            lambda i: api.styledmap.KumoyStyledMapDetail(
                id=i,
                name="map",
                description="",
                isPublic=False,
                projectId="p1",
                project=None,
                attribution="",
                assetsHash=None,
                thumbnailImageUrl="",
                createdAt="",
                updatedAt="",
                qgisproject="<qgis/>",
                role="OWNER",
            ),
        )
        out = tmp_path / "out.qgs"

        result = _run(GetMapAlgorithm(), {"MAP_ID": "m1", "PROJECT_FILE": str(out)})

        assert out.read_text(encoding="utf-8") == "<qgis/>"
        assert result["PROJECT_FILE"] == str(out)
        assert "qgisproject" not in result["MAP"]


@pytest.mark.usefixtures("qgis_plugin_path")
class TestUploadProjectId:
    @pytest.fixture(params=["vector", "raster"])
    def alg(self, request, api, monkeypatch):
        if request.param == "vector":
            from plugin_dir.processing.vector.upload import algorithm
        else:
            from plugin_dir.processing.raster.upload import algorithm

        monkeypatch.setattr(algorithm, "get_token", lambda: "token")
        org = SimpleNamespace(id="o1", name="Org", scheduledDeletionAt=None)
        monkeypatch.setattr(api.organization, "get_organizations", lambda: [org])
        monkeypatch.setattr(
            api.project,
            "get_projects_by_organization",
            lambda _: [
                SimpleNamespace(id="p1", name="A"),
                SimpleNamespace(id="p2", name="B"),
            ],
        )

        alg = (
            algorithm.UploadVectorAlgorithm()
            if request.param == "vector"
            else algorithm.UploadRasterAlgorithm()
        )
        alg.initAlgorithm()
        return alg

    def test_project_id_overrides_enum(self, alg):
        project_id = alg._resolve_project_id(
            {"PROJECT_ID": " p9 ", "PROJECT": 1}, QgsProcessingContext()
        )
        assert project_id == "p9"

    def test_falls_back_to_enum(self, alg):
        project_id = alg._resolve_project_id({"PROJECT": 1}, QgsProcessingContext())
        assert project_id == "p2"


@pytest.mark.usefixtures("qgis_plugin_path")
class TestSelectedProject:
    """Kumoy treats a project as the data boundary, as the Browser panel does."""

    def test_no_selected_project_fails(self, monkeypatch):
        from plugin_dir.processing.organization.get_project import GetProjectAlgorithm

        _select_project(monkeypatch, "")

        with pytest.raises(QgsProcessingException, match="No Kumoy project"):
            _run(GetProjectAlgorithm(), {})

    def test_get_vector_of_other_project_fails(self, api, monkeypatch):
        from plugin_dir.processing.vector.get import GetVectorAlgorithm

        monkeypatch.setattr(
            api.vector, "get_vector", lambda _: SimpleNamespace(projectId="p2")
        )

        with pytest.raises(QgsProcessingException, match="selected Kumoy project"):
            _run(GetVectorAlgorithm(), {"VECTOR_ID": "v1"})

    @pytest.mark.parametrize(
        "module, api_name, alg_name, getter, mutator, parameters",
        [
            (
                "vector.update",
                "vector",
                "UpdateVectorAlgorithm",
                "get_vector",
                "update_vector",
                {"VECTOR_ID": "v1", "NAME": "n"},
            ),
            (
                "vector.delete",
                "vector",
                "DeleteVectorAlgorithm",
                "get_vector",
                "delete_vector",
                {"VECTOR_ID": "v1"},
            ),
            (
                "raster.update",
                "raster",
                "UpdateRasterAlgorithm",
                "get_raster",
                "update_raster",
                {"RASTER_ID": "r1", "NAME": "n"},
            ),
            (
                "raster.delete",
                "raster",
                "DeleteRasterAlgorithm",
                "get_raster",
                "delete_raster",
                {"RASTER_ID": "r1"},
            ),
            (
                "map.update",
                "styledmap",
                "UpdateMapAlgorithm",
                "get_styled_map",
                "update_styled_map",
                {"MAP_ID": "m1", "NAME": "n"},
            ),
            (
                "map.delete",
                "styledmap",
                "DeleteMapAlgorithm",
                "get_styled_map",
                "delete_styled_map",
                {"MAP_ID": "m1"},
            ),
        ],
    )
    def test_other_project_is_not_modified(
        self, api, monkeypatch, module, api_name, alg_name, getter, mutator, parameters
    ):
        import importlib

        alg_module = importlib.import_module(f"plugin_dir.processing.{module}")
        api_module = getattr(api, api_name)
        monkeypatch.setattr(
            api_module, getter, lambda _: SimpleNamespace(projectId="p2")
        )
        called = []
        monkeypatch.setattr(api_module, mutator, lambda *a: called.append(a))

        with pytest.raises(QgsProcessingException, match="selected Kumoy project"):
            _run(getattr(alg_module, alg_name)(), parameters)

        assert called == []

    def test_create_map_goes_to_selected_project(self, api, monkeypatch):
        from plugin_dir.processing.map.create import CreateMapAlgorithm

        _select_project(monkeypatch, "p9")
        captured = {}

        def fake(project_id, options):
            captured["project_id"] = project_id
            return {"id": "m1"}

        monkeypatch.setattr(api.styledmap, "add_styled_map", fake)

        _run(CreateMapAlgorithm(), {"NAME": "map"})

        assert captured["project_id"] == "p9"
