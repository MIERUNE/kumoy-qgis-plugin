"""Tests for the Processing map tools (processing/map/), with the API replaced."""

import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProject,
)


def _run(alg, parameters):
    """Run like processing.run() does, but in-process so monkeypatches apply."""
    alg.initAlgorithm()
    return alg.processAlgorithm(
        parameters, QgsProcessingContext(), QgsProcessingFeedback()
    )


@pytest.fixture
def api(qgis_plugin_path, monkeypatch):
    from plugin_dir.kumoy import api, session, settings_manager

    # Logged in, with project p1 selected
    monkeypatch.setattr(session, "_token", "token")
    previous = (
        settings_manager.selected_organization_id(),
        settings_manager.selected_project_id(),
    )
    settings_manager.select_project("o1", "p1")
    yield api
    settings_manager.select_project(*previous)


@pytest.fixture
def server(api, monkeypatch):
    """Records the map API calls; update / create return plain maps."""
    calls = SimpleNamespace(created=[], updated=[], deleted=[], current=None)

    def create(project_id, **fields):
        calls.created.append((project_id, fields))
        return api.models.StyledMap(id="m1", name=fields["name"], projectId=project_id)

    def update(map_id, **changes):
        calls.updated.append((map_id, changes))
        return api.models.StyledMap(id=map_id, name="map", projectId="p1")

    monkeypatch.setattr(api.styledmap, "create_styled_map", create)
    monkeypatch.setattr(api.styledmap, "update_styled_map", update)
    monkeypatch.setattr(api.styledmap, "delete_styled_map", calls.deleted.append)
    monkeypatch.setattr(
        api.styledmap,
        "get_styled_map",
        lambda map_id: api.models.StyledMapDetail(
            id=map_id,
            name="map",
            projectId="p1",
            assetsHash=calls.current,
            qgisproject="<qgis/>",
            role="ADMIN",
        ),
    )
    return calls


@pytest.fixture
def uploads(api, monkeypatch, fake_kumoy_provider):
    from plugin_dir.processing.map import create, update

    uploads = []
    for module in (create, update):
        monkeypatch.setattr(
            module,
            "upload_sprites",
            lambda map_id, sprite: uploads.append((map_id, sprite.assets_hash)),
        )
    return uploads


def _create_alg():
    from plugin_dir.processing.map.create import CreateMapAlgorithm

    return CreateMapAlgorithm()


def _update_alg():
    from plugin_dir.processing.map.update import UpdateMapAlgorithm

    return UpdateMapAlgorithm()


class TestCreate:
    def test_without_file_uploads_empty_project(self, server):
        result = _run(_create_alg(), {"NAME": "map", "IS_PUBLIC": True})

        ((project_id, fields),) = server.created
        assert project_id == "p1"
        assert "<qgis" in fields["qgisproject"]
        assert fields["isPublic"] is True
        assert fields["description"] == ""
        # The project XML is too large to return as a result
        assert "qgisproject" not in result["MAP"]
        assert result["MAP"]["id"] == "m1"

    def test_requires_name(self, server):
        with pytest.raises(QgsProcessingException, match="required"):
            _run(_create_alg(), {"NAME": ""})

    def test_goes_to_selected_project(self, server, api):
        from plugin_dir.kumoy import settings_manager

        settings_manager.select_project("o1", "p9")

        _run(_create_alg(), {"NAME": "map"})

        assert server.created[0][0] == "p9"

    def test_uploads_sprites_of_project_file(self, server, uploads, tmp_path):
        from .project_files import write_kumoy_point_project

        path = write_kumoy_point_project(tmp_path)

        _run(_create_alg(), {"NAME": "map", "PROJECT_FILE": str(path)})

        new_hash = server.updated[0][1]["assetsHash"]
        assert new_hash is not None
        assert uploads == [("m1", new_hash)]

    def test_deletes_map_when_sprite_upload_fails(
        self, server, uploads, monkeypatch, tmp_path
    ):
        from plugin_dir.processing.map import create

        from .project_files import write_kumoy_point_project

        def fail(*_):
            raise RuntimeError("upload failed")

        monkeypatch.setattr(create, "upload_sprites", fail)
        path = write_kumoy_point_project(tmp_path)

        with pytest.raises(QgsProcessingException, match="upload failed"):
            _run(_create_alg(), {"NAME": "map", "PROJECT_FILE": str(path)})

        assert server.deleted == ["m1"]


class TestUpdate:
    def test_reads_project_from_qgz(self, server, uploads, tmp_path):
        from .project_files import to_qgz, write_kumoy_point_project

        qgz = to_qgz(write_kumoy_point_project(tmp_path))

        _run(_update_alg(), {"MAP_ID": "m1", "PROJECT_FILE": str(qgz)})

        changes = server.updated[0][1]
        assert "vector_id=v1" in changes["qgisproject"]
        assert "isPublic" not in changes

    def test_uploads_sprites_of_project_file(self, server, uploads, tmp_path):
        from .project_files import fixed_aspect_ratios, write_kumoy_point_project

        server.current = "old"
        path = write_kumoy_point_project(tmp_path)

        _run(_update_alg(), {"MAP_ID": "m1", "PROJECT_FILE": str(path)})

        changes = server.updated[0][1]
        assert changes["assetsHash"] not in (None, "old")
        assert uploads == [("m1", changes["assetsHash"])]
        assert fixed_aspect_ratios(changes["qgisproject"]) == ["0.5"]

    def test_skips_unchanged_sprites(self, server, uploads, tmp_path):
        from plugin_dir.kumoy import map_project
        from plugin_dir.kumoy.sprite import generate_sprite

        from .project_files import write_kumoy_point_project

        path = write_kumoy_point_project(tmp_path)
        server.current = generate_sprite(
            map_project.read_project_file(str(path))
        ).assets_hash

        _run(_update_alg(), {"MAP_ID": "m1", "PROJECT_FILE": str(path)})

        assert uploads == []
        assert "assetsHash" not in server.updated[0][1]

    def test_clears_sprites_without_point_symbols(self, server, uploads, tmp_path):
        server.current = "old"
        path = str(tmp_path / "empty.qgs")
        QgsProject().write(path)

        _run(_update_alg(), {"MAP_ID": "m1", "PROJECT_FILE": path})

        assert uploads == []
        assert server.updated[0][1]["assetsHash"] is None

    @pytest.mark.parametrize("index, expected", [(1, True), (2, False)])
    def test_visibility(self, server, index, expected):
        _run(_update_alg(), {"MAP_ID": "m1", "IS_PUBLIC": index})

        assert server.updated[0][1] == {"isPublic": expected}

    def test_sends_only_given_fields(self, server):
        _run(_update_alg(), {"MAP_ID": "m1", "NAME": "new"})

        assert server.updated[0][1] == {"name": "new"}

    def test_without_changes_fails(self, server):
        with pytest.raises(QgsProcessingException, match="Nothing to update"):
            _run(_update_alg(), {"MAP_ID": "m1"})


class TestGetListDelete:
    def test_get_writes_project_file(self, server, tmp_path):
        from plugin_dir.processing.map.get import GetMapAlgorithm

        out = tmp_path / "out.qgs"

        result = _run(GetMapAlgorithm(), {"MAP_ID": "m1", "PROJECT_FILE": str(out)})

        assert out.read_text(encoding="utf-8") == "<qgis/>"
        assert result["PROJECT_FILE"] == str(out)
        assert "qgisproject" not in result["MAP"]

    def test_list_passes_project_id(self, api, monkeypatch):
        from plugin_dir.processing.map.list import ListMapsAlgorithm

        monkeypatch.setattr(
            api.styledmap,
            "get_styled_maps",
            lambda project_id: [api.models.StyledMap(id="m1", name=project_id)],
        )

        result = _run(ListMapsAlgorithm(), {"PROJECT_ID": "p5"})

        assert [m["name"] for m in result["MAPS"]] == ["p5"]

    def test_delete_clears_old_cache_file(self, server, monkeypatch):
        from plugin_dir.kumoy.local_cache import map as map_cache
        from plugin_dir.processing.map.delete import DeleteMapAlgorithm

        cleared = []
        monkeypatch.setattr(map_cache, "clear", lambda i: cleared.append(i) or True)

        result = _run(DeleteMapAlgorithm(), {"MAP_ID": "m1"})

        assert server.deleted == ["m1"] == cleared
        assert result["MAP_ID"] == "m1"


class TestMainThread:
    @pytest.mark.parametrize(
        "module, name, expected",
        [
            ("create", "CreateMapAlgorithm", True),
            ("update", "UpdateMapAlgorithm", True),
            ("get", "GetMapAlgorithm", False),
            ("list", "ListMapsAlgorithm", False),
        ],
    )
    def test_flag_and_help_match(self, api, module, name, expected):
        import importlib

        module = importlib.import_module(f"plugin_dir.processing.map.{module}")
        algorithm = getattr(module, name)()

        no_threading = bool(
            algorithm.flags() & Qgis.ProcessingAlgorithmFlag.NoThreading
        )
        assert no_threading is expected
        # Script authors calling processing.run() are not covered by the flag
        assert ("main thread" in algorithm.shortHelpString()) is expected


class TestProjectFileMapCanvas:
    """Kumoy opens a map at the extent of <mapcanvas name="theMapCanvas">."""

    @staticmethod
    def _canvas_extents(qgisproject):
        return [
            [
                float(e.find("extent").find(k).text)
                for k in ("xmin", "ymin", "xmax", "ymax")
            ]
            for e in ET.fromstring(qgisproject).iter("mapcanvas")
            if e.get("name") == "theMapCanvas"
        ]

    @staticmethod
    def _project(tmp_path, configure=lambda project: None):
        project = QgsProject()
        project.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        configure(project)
        path = tmp_path / "project.qgs"
        project.write(str(path))
        return path

    def _load(self, api, path):
        from plugin_dir.processing.map._project_file import load_project_file

        return load_project_file(str(path)).qgisproject

    def test_map_canvas_of_file_is_kept(self, api, tmp_path):
        path = self._project(tmp_path)
        # As QGIS writes it when saving from the GUI
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "</qgis>",
                '<mapcanvas name="theMapCanvas"><units>degrees</units><extent>'
                "<xmin>139</xmin><ymin>35</ymin><xmax>140</xmax><ymax>36</ymax>"
                "</extent><rotation>0</rotation></mapcanvas></qgis>",
            ),
            encoding="utf-8",
        )

        assert self._canvas_extents(self._load(api, path)) == [[139, 35, 140, 36]]

    def test_default_view_extent_is_used_in_project_crs(self, api, tmp_path):
        from qgis.core import QgsRectangle, QgsReferencedRectangle

        path = self._project(
            tmp_path,
            lambda project: project.viewSettings().setDefaultViewExtent(
                QgsReferencedRectangle(
                    QgsRectangle(15473000, 4163000, 15585000, 4300000),
                    QgsCoordinateReferenceSystem("EPSG:3857"),
                )
            ),
        )

        ((xmin, ymin, xmax, ymax),) = self._canvas_extents(self._load(api, path))
        assert (xmin, xmax) == (
            pytest.approx(139.0, abs=0.01),
            pytest.approx(140.0, abs=0.01),
        )
        assert (ymin, ymax) == (
            pytest.approx(35.0, abs=0.1),
            pytest.approx(36.0, abs=0.1),
        )

    def test_project_without_extent_has_no_map_canvas(self, api, tmp_path):
        assert self._canvas_extents(self._load(api, self._project(tmp_path))) == []

    def test_open_project_is_not_affected(self, api, tmp_path):
        self._load(api, self._project(tmp_path))

        out = tmp_path / "open.qgs"
        QgsProject.instance().write(str(out))
        assert 'name="theMapCanvas"' not in out.read_text(encoding="utf-8")

    def test_too_large_file_fails(self, api, tmp_path, monkeypatch):
        from plugin_dir.kumoy import map_project

        monkeypatch.setattr(map_project, "MAX_QGISPROJECT_LENGTH", 10)

        with pytest.raises(QgsProcessingException, match="too large"):
            self._load(api, self._project(tmp_path))
