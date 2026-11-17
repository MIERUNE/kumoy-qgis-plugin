"""Tests for ui/project_storage.py: Kumoy maps as "kumoy:<map id>" projects.

The API, the conversion of local layers and the dialogs are replaced; QGIS's
own project reading and writing runs for real.
"""

from types import SimpleNamespace

import pytest
from qgis.core import (
    QgsApplication,
    QgsCoordinateTransformContext,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
)


def _gpkg(path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    QgsVectorFileWriter.writeAsVectorFormatV3(
        QgsVectorLayer("Point?crs=EPSG:4326", "points", "memory"),
        str(path),
        QgsCoordinateTransformContext(),
        QgsVectorFileWriter.SaveVectorOptions(),
    )
    return str(path)


def _project_xml(path, layer_source: str, absolute: bool = True) -> str:
    """XML of a project with one GeoPackage layer, written at path."""
    project = QgsProject()
    project.writeEntry("Paths", "/Absolute", absolute)
    project.addMapLayer(QgsVectorLayer(layer_source, "points", "ogr"))
    assert project.write(str(path))
    return path.read_text(encoding="utf-8")


class FakeApi:
    """The server: maps by ID, and what the plugin sent."""

    def __init__(self, api):
        self.models = api.models
        self.maps = {}
        self.updates = []
        self.fail_with = None

    def add(self, map_id, qgisproject="", role="ADMIN", project_id="p1", **kwargs):
        self.maps[map_id] = self.models.StyledMapDetail(
            id=map_id,
            name=kwargs.pop("name", f"Map {map_id}"),
            projectId=project_id,
            qgisproject=qgisproject,
            role=role,
            **kwargs,
        )

    def get_styled_map(self, map_id):
        if self.fail_with is not None:
            raise self.fail_with
        return self.maps[map_id]

    def update_styled_map(self, map_id, **changes):
        if self.fail_with is not None:
            raise self.fail_with
        self.updates.append((map_id, changes))
        current = self.maps[map_id]
        return self.models.StyledMap(id=map_id, name=current.name, projectId="p1")


class FakeMessageBox:
    answer = None  # set per test
    questions = []
    warnings = []

    @classmethod
    def question(cls, parent, title, text, *_):
        cls.questions.append(text)
        return cls.answer

    @classmethod
    def warning(cls, parent, title, text):
        cls.warnings.append(text)


@pytest.fixture
def storage(qgis_plugin_path, qgis_app, monkeypatch, tmp_path):
    from plugin_dir.kumoy import api
    from plugin_dir.kumoy.local_cache import map as map_cache
    from plugin_dir.pyqt_version import Q_MESSAGEBOX_STD_BUTTON
    from plugin_dir.ui import project_storage

    fake = FakeApi(api)
    monkeypatch.setattr(api.styledmap, "get_styled_map", fake.get_styled_map)
    monkeypatch.setattr(api.styledmap, "update_styled_map", fake.update_styled_map)

    FakeMessageBox.answer = Q_MESSAGEBOX_STD_BUTTON.No
    FakeMessageBox.questions = []
    FakeMessageBox.warnings = []
    monkeypatch.setattr(project_storage, "QMessageBox", FakeMessageBox)

    successes = []
    monkeypatch.setattr(project_storage, "push_success", successes.append)
    sprite_uploads = []
    monkeypatch.setattr(
        project_storage,
        "upload_sprites",
        lambda map_id, sprite: sprite_uploads.append((map_id, sprite.assets_hash)),
    )
    conversion = SimpleNamespace(
        cancelled=False, errors=[], converted=False, skipped=[]
    )
    monkeypatch.setattr(
        project_storage, "convert_local_layers", lambda project_id: conversion
    )
    message_bar = []
    monkeypatch.setattr(
        project_storage,
        "iface",
        SimpleNamespace(
            messageBar=lambda: SimpleNamespace(
                pushMessage=lambda *args: message_bar.append(args)
            ),
            mainWindow=lambda: None,
        ),
    )

    cache_dir = tmp_path / "cache" / "maps"
    cache_dir.mkdir(parents=True)
    monkeypatch.setattr(map_cache, "get_cache_dir", lambda: str(cache_dir))

    QgsProject.instance().clear()
    project_storage.register()
    yield SimpleNamespace(
        module=project_storage,
        api=fake,
        successes=successes,
        sprite_uploads=sprite_uploads,
        conversion=conversion,
        message_bar=message_bar,
        cache_dir=cache_dir,
        tmp_path=tmp_path,
    )
    project_storage.unregister()
    QgsProject.instance().clear()


def _open(storage, map_id="m1", **kwargs):
    """Add map_id to the server with one local layer and open it."""
    if map_id not in storage.api.maps:
        gpkg = _gpkg(storage.tmp_path / "data" / "points.gpkg")
        xml = _project_xml(storage.tmp_path / f"{map_id}.qgs", gpkg)
        storage.api.add(map_id, xml, **kwargs)
    project = QgsProject.instance()
    assert project.read(f"kumoy:{map_id}"), project.error()
    QgsApplication.processEvents()
    return project


def _layer_names(project):
    return sorted(layer.name() for layer in project.mapLayers().values())


class TestRead:
    def test_opens_map(self, storage):
        project = _open(storage)

        assert _layer_names(project) == ["points"]
        assert project.fileName() == "kumoy:m1"
        assert project.title() == "Map m1"
        assert not project.isDirty()

    def test_failure_is_reported(self, storage):
        from plugin_dir.kumoy.api.error import NetworkError

        storage.api.fail_with = NetworkError("Network Error", "offline")

        assert not QgsProject.instance().read("kumoy:m1")
        assert "offline" in QgsProject.instance().error()

    def test_relative_paths_of_old_plugin_versions(self, storage):
        """Old versions wrote the XML next to the map's cache file."""
        gpkg = _gpkg(storage.cache_dir.parent / "data" / "points.gpkg")
        xml = _project_xml(storage.cache_dir / "written.qgs", gpkg, absolute=False)
        assert "<datasource>../data/points.gpkg</datasource>" in xml
        storage.api.add("m1", xml)

        project = _open(storage)

        (layer,) = project.mapLayers().values()
        assert layer.isValid()
        assert layer.source() == gpkg

        # Saved again with absolute paths: the cache file is gone with this version
        project.setDirty(True)
        assert project.write()
        assert (
            f"<datasource>{gpkg}</datasource>"
            in storage.api.updates[-1][1]["qgisproject"]
        )

    def test_offers_to_select_the_maps_project(self, storage, monkeypatch):
        from plugin_dir.kumoy import settings_manager
        from plugin_dir.pyqt_version import Q_MESSAGEBOX_STD_BUTTON

        selected = []
        monkeypatch.setattr(settings_manager, "selected_project_id", lambda: "p0")
        monkeypatch.setattr(
            settings_manager, "select_project", lambda *ids: selected.append(ids)
        )
        monkeypatch.setattr(storage.module, "refresh_kumoy_browser", lambda: None)
        FakeMessageBox.answer = Q_MESSAGEBOX_STD_BUTTON.Yes
        team = storage.api.models.Team(id="t1", name="team", organizationId="o1")
        project = storage.api.models.Project(id="p1", name="Other", team=team)

        opened = _open(storage, project=project)

        assert len(FakeMessageBox.questions) == 1
        assert selected == [("o1", "p1")]
        # Nothing is closed or changed
        assert _layer_names(opened) == ["points"]

    def test_no_offer_for_the_selected_project(self, storage, monkeypatch):
        from plugin_dir.kumoy import settings_manager

        monkeypatch.setattr(settings_manager, "selected_project_id", lambda: "p1")
        team = storage.api.models.Team(id="t1", name="team", organizationId="o1")
        project = storage.api.models.Project(id="p1", name="Same", team=team)

        _open(storage, project=project)

        assert FakeMessageBox.questions == []


class TestWrite:
    def test_saves_map(self, storage):
        project = _open(storage)
        source = next(iter(project.mapLayers().values())).source()
        project.addMapLayer(QgsVectorLayer(source, "copy", "ogr"))
        project.setDirty(True)

        assert project.write(), project.error()

        ((map_id, changes),) = storage.api.updates
        assert map_id == "m1"
        assert "<layername>copy</layername>" in changes["qgisproject"]
        # No point symbols, and the map has no sprite: nothing to change
        assert "assetsHash" not in changes
        assert project.fileName() == "kumoy:m1"
        assert not project.isDirty()
        assert storage.successes

    def _cannot_save(self, storage, project, message):
        project.setDirty(True)

        assert not project.write()

        assert project.isDirty()
        assert project.fileName() == "kumoy:m1"
        assert message in project.error()
        assert storage.api.updates == []

    def test_viewer_cannot_save(self, storage):
        project = _open(storage, role="MEMBER")

        self._cannot_save(storage, project, "Viewer")

    def test_api_error_keeps_changes(self, storage):
        from plugin_dir.kumoy.api.error import NetworkError

        project = _open(storage)
        storage.api.fail_with = NetworkError("Network Error", "offline")

        self._cannot_save(storage, project, "offline")

    def test_too_large(self, storage, monkeypatch):
        from plugin_dir.kumoy import map_project

        project = _open(storage)
        monkeypatch.setattr(map_project, "MAX_QGISPROJECT_LENGTH", 100)

        self._cannot_save(storage, project, "too large")

    def test_canceled_conversion(self, storage):
        project = _open(storage)
        storage.conversion.cancelled = True

        self._cannot_save(storage, project, "canceled")
        # Canceled by the user: nothing to report outside the save itself
        assert storage.module._storage.last_error is None

    def test_layers_of_another_project(self, storage, fake_kumoy_provider):
        from plugin_dir.kumoy.constants import DATA_PROVIDER_KEY

        project = _open(storage)
        project.addMapLayer(
            QgsVectorLayer(
                "project_id=p2;vector_id=v1;vector_name=x;vector_type=POINT;",
                "foreign",
                DATA_PROVIDER_KEY,
            )
        )

        self._cannot_save(storage, project, "foreign")

    def test_conversion_result_is_saved(self, storage, monkeypatch):
        project = _open(storage)
        storage.conversion.converted = True
        project.setDirty(True)

        def convert(project_id):
            # As the real conversion does: the local layer becomes another one
            layer = next(iter(project.mapLayers().values()))
            layer.setName("converted")
            return storage.conversion

        monkeypatch.setattr(storage.module, "convert_local_layers", convert)
        assert project.write(), project.error()

        xml = storage.api.updates[0][1]["qgisproject"]
        assert "<layername>converted</layername>" in xml

    @pytest.mark.parametrize(
        "server_hash, uploaded", [("old", [("m1", "new")]), ("new", [])]
    )
    def test_sprite_uploaded_when_changed(
        self, storage, monkeypatch, server_hash, uploaded
    ):
        from plugin_dir.kumoy.sprite import SpriteData

        monkeypatch.setattr(
            storage.module,
            "generate_sprite",
            lambda project: SpriteData(b"{}", b"png", "new"),
        )
        project = _open(storage, assetsHash=server_hash)
        project.setDirty(True)

        assert project.write(), project.error()

        assert storage.sprite_uploads == uploaded
        changes = storage.api.updates[0][1]
        assert changes.get("assetsHash", "new") == "new"
        assert ("assetsHash" in changes) == bool(uploaded)

    def test_sprite_cleared_without_point_symbols(self, storage):
        project = _open(storage, assetsHash="old")
        project.setDirty(True)

        assert project.write(), project.error()

        assert storage.api.updates[0][1]["assetsHash"] is None


class TestSymbolEmbedding:
    def _add_icon_layer(self, project, tmp_path):
        from qgis.core import (
            QgsMarkerSymbol,
            QgsRasterMarkerSymbolLayer,
            QgsSingleSymbolRenderer,
        )
        from qgis.PyQt.QtCore import QSize
        from qgis.PyQt.QtGui import QColor, QImage

        from plugin_dir.pyqt_version import Q_IMAGE_FORMAT

        icon = tmp_path / "icon.png"
        image = QImage(QSize(8, 4), Q_IMAGE_FORMAT.Format_ARGB32)
        image.fill(QColor(0, 0, 255, 255))
        assert image.save(str(icon))
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "icons", "memory")
        layer.setRenderer(
            QgsSingleSymbolRenderer(
                QgsMarkerSymbol([QgsRasterMarkerSymbolLayer(str(icon))])
            )
        )
        project.addMapLayer(layer)
        return layer

    def _icon_path(self, layer):
        return layer.renderer().symbol().symbolLayer(0).path()

    def test_yes_embeds(self, storage):
        from plugin_dir.pyqt_version import Q_MESSAGEBOX_STD_BUTTON

        project = _open(storage)
        layer = self._add_icon_layer(project, storage.tmp_path)
        FakeMessageBox.answer = Q_MESSAGEBOX_STD_BUTTON.Yes

        assert project.write(), project.error()

        assert len(FakeMessageBox.questions) == 1
        assert self._icon_path(layer).startswith("base64:")
        assert "base64:" in storage.api.updates[0][1]["qgisproject"]

    def test_no_is_not_asked_again_for_the_same_files(self, storage):
        project = _open(storage)
        layer = self._add_icon_layer(project, storage.tmp_path)

        assert project.write(), project.error()
        project.setDirty(True)
        assert project.write(), project.error()

        assert len(FakeMessageBox.questions) == 1
        assert not self._icon_path(layer).startswith("base64:")
        assert len(storage.api.updates) == 2

    def test_not_offered_when_embedding_exceeds_the_limit(self, storage, monkeypatch):
        from plugin_dir.kumoy import api, map_project

        project = _open(storage)
        layer = self._add_icon_layer(project, storage.tmp_path)
        # Room for the project, not for the embedded icon
        size = len(map_project.write_xml(project)) + 30
        project.setFileName("kumoy:m1")
        monkeypatch.setattr(api.styledmap, "MAX_QGISPROJECT_LENGTH", size)
        monkeypatch.setattr(map_project, "MAX_QGISPROJECT_LENGTH", size)

        project.write()

        assert FakeMessageBox.questions == []
        assert len(FakeMessageBox.warnings) == 1
        assert not self._icon_path(layer).startswith("base64:")


class TestSaveToMap:
    def test_links_project_to_the_map(self, storage):
        project = _open(storage)
        storage.api.add("m2", "")

        assert storage.module.save_to_map("m2")

        assert project.fileName() == "kumoy:m2"
        assert storage.api.updates[0][0] == "m2"
        assert not project.isDirty()

    def test_failure_keeps_the_previous_link(self, storage):
        project = _open(storage)
        storage.api.add("m2", "", role="MEMBER")

        assert not storage.module.save_to_map("m2")

        assert project.fileName() == "kumoy:m1"
        assert project.isDirty()
        ((title, message, *_),) = storage.message_bar
        assert "Viewer" in message

    def test_unlink_keeps_the_project(self, storage):
        project = _open(storage)
        project.setDirty(True)

        storage.module.unlink_map("m1")

        assert project.fileName() == ""
        assert project.isDirty()
        assert _layer_names(project) == ["points"]


class TestOpenMap:
    @pytest.fixture
    def tasks(self, storage, monkeypatch):
        def run_task(description, fn, on_success=None, on_error=None, **_):
            try:
                result = fn(None)
            except Exception as e:
                on_error(e)
            else:
                on_success(result)

        monkeypatch.setattr(storage.module, "run_task", run_task)
        errors = []
        monkeypatch.setattr(
            storage.module, "handle_api_error", lambda e, **_: errors.append(e)
        )
        added = []

        def add_project(uri):
            added.append(uri)
            return QgsProject.instance().read(uri)

        storage.module.iface.addProject = add_project
        storage.module.iface.newProject = lambda prompt: False  # user cancels
        return SimpleNamespace(errors=errors, added=added)

    def test_opens_with_one_request(self, storage, tasks, monkeypatch):
        calls = []
        get = storage.api.get_styled_map
        monkeypatch.setattr(
            storage.module.api.styledmap,
            "get_styled_map",
            lambda map_id: calls.append(map_id) or get(map_id),
        )
        gpkg = _gpkg(storage.tmp_path / "a.gpkg")
        storage.api.add("m1", _project_xml(storage.tmp_path / "x.qgs", gpkg))

        storage.module.open_map("m1")

        assert tasks.added == ["kumoy:m1"]
        assert calls == ["m1"]
        assert QgsProject.instance().fileName() == "kumoy:m1"

    def test_failure_leaves_the_project_alone(self, storage, tasks):
        from plugin_dir.kumoy.api.error import NetworkError

        project = _open(storage)
        project.setDirty(True)
        storage.api.fail_with = NetworkError("Network Error", "offline")

        storage.module.open_map("m2")

        assert len(tasks.errors) == 1
        assert tasks.added == []
        assert project.fileName() == "kumoy:m1"
        assert project.isDirty()

    def test_unsaved_changes_prompt_can_cancel(self, storage, tasks):
        project = _open(storage)
        project.setDirty(True)
        storage.api.add("m2", "")

        storage.module.open_map("m2")

        assert tasks.added == []
        assert project.fileName() == "kumoy:m1"


class TestLegacyCacheFile:
    def test_switches_to_the_map(self, storage, monkeypatch):
        opened = []
        monkeypatch.setattr(storage.module, "open_map", opened.append)
        gpkg = _gpkg(storage.cache_dir.parent / "data" / "points.gpkg")
        path = storage.cache_dir / "m1.qgs"
        _project_xml(path, gpkg, absolute=False)

        project = QgsProject.instance()
        assert project.read(str(path))
        QgsApplication.processEvents()

        assert project.fileName() == "kumoy:m1"
        assert not project.isDirty()
        assert _layer_names(project) == ["points"]
        # Then reloaded from Kumoy, for changes saved since the file was written
        assert opened == ["m1"]

    def test_other_files_are_left_alone(self, storage, monkeypatch):
        opened = []
        monkeypatch.setattr(storage.module, "open_map", opened.append)
        path = storage.tmp_path / "m1.qgs"
        _project_xml(path, _gpkg(storage.tmp_path / "a.gpkg"))

        assert QgsProject.instance().read(str(path))
        QgsApplication.processEvents()

        assert QgsProject.instance().fileName() == str(path)
        assert opened == []


def test_write_xml_keeps_local_paths_absolute(qgis_app, tmp_path, monkeypatch):
    """Data that shares a prefix with the temp dir (always the case on Windows,
    both under C:\\Users) must not be saved relative to the temp file."""
    import tempfile

    from qgis.core import Qgis, QgsProject, QgsVectorLayer

    from plugin_dir.kumoy import map_project

    # The temp dir and the data share a parent, as %TEMP% and Documents do
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "temp"))
    (tmp_path / "temp").mkdir()
    data = tmp_path / "docs" / "points.geojson"
    data.parent.mkdir()
    data.write_text('{"type":"FeatureCollection","features":[]}')

    project = QgsProject()
    project.setFilePathStorage(Qgis.FilePathType.Relative)
    project.addMapLayer(QgsVectorLayer(str(data), "points", "ogr"))
    xml = map_project.write_xml(project)

    assert f"<datasource>{data}</datasource>" in xml
    assert project.filePathStorage() == Qgis.FilePathType.Relative
