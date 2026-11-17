"""Tests for the map items of the Browser panel (ui/browser/styledmap.py)."""

from types import SimpleNamespace

import pytest
from qgis.core import QgsProject


@pytest.fixture
def browser(qgis_plugin_path, qgis_app, monkeypatch):
    from ._rewrite_shims import install

    install()
    from plugin_dir.kumoy import api
    from plugin_dir.ui.browser import styledmap

    def run_task(description, fn, on_success=None, on_error=None, **_):
        try:
            result = fn(SimpleNamespace(setProgress=lambda _: None))
        except Exception as e:
            on_error(e)
        else:
            on_success(result)

    monkeypatch.setattr(styledmap, "run_task", run_task)
    state = SimpleNamespace(
        module=styledmap,
        api=api,
        successes=[],
        warnings=[],
        errors=[],
        confirm=True,
        fields=None,
    )
    monkeypatch.setattr(styledmap, "push_success", state.successes.append)
    monkeypatch.setattr(
        styledmap, "handle_api_error", lambda e, **_: state.errors.append(e)
    )
    monkeypatch.setattr(styledmap, "_confirm", lambda title, text: state.confirm)
    monkeypatch.setattr(styledmap, "_ask_map_fields", lambda *_: state.fields)
    monkeypatch.setattr(
        styledmap,
        "QMessageBox",
        SimpleNamespace(
            warning=lambda parent, title, text: state.warnings.append(text)
        ),
    )
    QgsProject.instance().clear()
    yield state
    QgsProject.instance().clear()


def _item(browser, map_id="m1", **fields):
    styled_map = browser.api.models.StyledMap(id=map_id, name=f"Map {map_id}", **fields)
    return browser.module.StyledMapItem(None, f"/maps/{map_id}", styled_map, "ADMIN")


class TestEditMetadata:
    def _update(self, browser, monkeypatch, sent):
        def update(map_id, **fields):
            sent.append((map_id, fields))
            return browser.api.models.StyledMap(id=map_id, name=fields["name"])

        monkeypatch.setattr(browser.api.styledmap, "update_styled_map", update)

    def test_renames_open_map_and_keeps_unsaved_changes(self, browser, monkeypatch):
        sent = []
        self._update(browser, monkeypatch, sent)
        browser.fields = {"name": "New", "description": "", "attribution": ""}
        project = QgsProject.instance()
        project.setFileName("kumoy:m1")
        project.setDirty(True)

        item = _item(browser)
        item.edit_metadata()

        assert sent == [("m1", browser.fields)]
        assert item.name() == "New"
        assert project.title() == "New"
        # Renaming the map on the server does not save the open project
        assert project.isDirty()

    def test_other_project_is_untouched(self, browser, monkeypatch):
        self._update(browser, monkeypatch, [])
        browser.fields = {"name": "New"}
        project = QgsProject.instance()
        project.setFileName("kumoy:m2")
        project.setTitle("Mine")
        project.setDirty(False)

        _item(browser).edit_metadata()

        assert project.title() == "Mine"
        assert not project.isDirty()

    def test_shows_link_when_made_public(self, browser, monkeypatch):
        shown = []
        monkeypatch.setattr(browser.module, "show_public_url", shown.append)

        def update(map_id, **fields):
            return browser.api.models.StyledMap(id=map_id, name="m", isPublic=True)

        monkeypatch.setattr(browser.api.styledmap, "update_styled_map", update)
        browser.fields = {"name": "m", "isPublic": True}

        _item(browser).edit_metadata()

        assert [m.id for m in shown] == ["m1"]


class TestDelete:
    def test_partial_failure_is_reported(self, browser, monkeypatch):
        from plugin_dir.kumoy.api.error import NotFoundError

        deleted = []

        def delete(map_id):
            if map_id == "m2":
                raise NotFoundError("Not Found", "gone")
            deleted.append(map_id)

        monkeypatch.setattr(browser.api.styledmap, "delete_styled_map", delete)
        items = [_item(browser, i) for i in ("m1", "m2", "m3")]

        browser.module.delete_multiple_maps(items)

        assert deleted == ["m1", "m3"]
        (warning,) = browser.warnings
        assert "2 of 3" in warning and "Map m2" in warning
        assert browser.successes == []

    def test_stops_when_logged_out(self, browser, monkeypatch):
        from plugin_dir.kumoy.api.error import UnauthorizedError

        def delete(map_id):
            raise UnauthorizedError("Unauthorized", "expired")

        monkeypatch.setattr(browser.api.styledmap, "delete_styled_map", delete)
        items = [_item(browser, i) for i in ("m1", "m2")]

        browser.module.delete_multiple_maps(items)

        assert len(browser.errors) == 1
        assert "0 of 2" in browser.warnings[0]

    def test_open_map_stays_open_unlinked(self, browser, monkeypatch):
        monkeypatch.setattr(browser.api.styledmap, "delete_styled_map", lambda _: None)
        project = QgsProject.instance()
        project.setFileName("kumoy:m1")
        project.setDirty(True)

        _item(browser).delete()

        assert project.fileName() == ""
        assert project.isDirty()
        assert browser.successes


class TestOverwrite:
    def test_saves_after_confirmation(self, browser, monkeypatch):
        saved = []
        monkeypatch.setattr(browser.module.project_storage, "save_to_map", saved.append)

        _item(browser).overwrite()
        browser.confirm = False
        _item(browser).overwrite()

        assert saved == ["m1"]


class TestRoot:
    def test_children_of_its_project(self, browser, monkeypatch):
        asked = []
        monkeypatch.setattr(
            browser.api.styledmap,
            "get_styled_maps",
            lambda project_id: (
                asked.append(project_id)
                or [browser.api.models.StyledMap(id="m1", name="Map")]
            ),
        )
        project = browser.api.models.ProjectDetail(id="p1", name="P", role="MEMBER")
        root = browser.module.StyledMapRoot(None, "Maps", "/maps", None, project)

        (child,) = root.createChildren()

        assert asked == ["p1"]
        assert child.styled_map.id == "m1"
        assert child.role == "MEMBER"
