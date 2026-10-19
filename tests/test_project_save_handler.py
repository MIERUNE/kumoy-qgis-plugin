"""confirm_symbol_embedding のテスト（ユーザー確認 → 埋め込み）"""

import pytest


@pytest.mark.usefixtures("qgis_plugin_path")
class TestConfirmSymbolEmbedding:
    @pytest.fixture
    def project(self, qgis_app):
        from qgis.core import QgsProject

        project = QgsProject.instance()
        project.clear()
        yield project
        project.clear()

    @pytest.fixture
    def ask(self, monkeypatch, qgis_app):
        """Replace the dialogs: ask.answer is what the user clicks, ask.calls the
        asks, ask.warnings the warnings shown."""
        from plugin_dir.pyqt_version import Q_MESSAGEBOX_STD_BUTTON
        from plugin_dir.ui import project_save_handler

        class _Ask:
            answer = Q_MESSAGEBOX_STD_BUTTON.Yes
            calls = 0
            warnings = 0

        ask = _Ask()

        class _FakeMessageBox:
            @staticmethod
            def question(parent, title, text, buttons, default):
                ask.calls += 1
                return ask.answer

            @staticmethod
            def warning(parent, title, text):
                ask.warnings += 1

        monkeypatch.setattr(project_save_handler, "QMessageBox", _FakeMessageBox)
        return ask

    def _project_with_icon(self, project, tmp_path):
        from plugin_dir.pyqt_version import Q_IMAGE_FORMAT
        from qgis.core import (
            QgsMarkerSymbol,
            QgsRasterMarkerSymbolLayer,
            QgsSingleSymbolRenderer,
            QgsVectorLayer,
        )
        from qgis.PyQt.QtCore import QSize
        from qgis.PyQt.QtGui import QColor, QImage

        icon = tmp_path / "icon.png"
        img = QImage(QSize(8, 4), Q_IMAGE_FORMAT.Format_ARGB32)
        img.fill(QColor(0, 0, 255, 255))
        saved = img.save(str(icon))
        assert saved
        symbol_layer = QgsRasterMarkerSymbolLayer(str(icon))
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "layer", "memory")
        layer.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol([symbol_layer])))
        project.addMapLayer(layer)
        return layer, str(icon)

    def _icon_path(self, layer):
        return layer.renderer().symbol().symbolLayer(0).path()

    def test_does_not_ask_without_local_symbol_files(self, project, ask):
        from plugin_dir.ui.project_save_handler import confirm_symbol_embedding
        from qgis.core import QgsMarkerSymbol, QgsSingleSymbolRenderer, QgsVectorLayer

        layer = QgsVectorLayer("Point?crs=EPSG:4326", "layer", "memory")
        layer.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({})))
        project.addMapLayer(layer)

        confirm_symbol_embedding(project)

        assert ask.calls == 0

    def test_yes_embeds_the_files(self, project, ask, tmp_path):
        from plugin_dir.ui.project_save_handler import confirm_symbol_embedding

        layer, _ = self._project_with_icon(project, tmp_path)

        confirm_symbol_embedding(project)

        assert ask.calls == 1
        assert self._icon_path(layer).startswith("base64:")

    def test_no_keeps_the_paths(self, project, ask, tmp_path):
        from plugin_dir.pyqt_version import Q_MESSAGEBOX_STD_BUTTON
        from plugin_dir.ui.project_save_handler import confirm_symbol_embedding

        ask.answer = Q_MESSAGEBOX_STD_BUTTON.No
        layer, icon = self._project_with_icon(project, tmp_path)

        confirm_symbol_embedding(project)

        assert ask.calls == 1
        assert self._icon_path(layer) == icon

    def test_does_not_ask_again_after_yes(self, project, ask, tmp_path):
        from plugin_dir.ui.project_save_handler import confirm_symbol_embedding

        self._project_with_icon(project, tmp_path)

        confirm_symbol_embedding(project)
        confirm_symbol_embedding(project)

        assert ask.calls == 1

    def _set_limit_above_current_size(self, monkeypatch, offset):
        """Set the size limit to the current project size plus ``offset``."""
        from plugin_dir.kumoy.local_cache import map as cache_map

        size = len(cache_map.serialize_project())
        monkeypatch.setattr(cache_map, "LENGTH_LIMIT", size + offset)

    def test_does_not_offer_when_embedding_would_exceed_the_limit(
        self, project, ask, tmp_path, monkeypatch
    ):
        from plugin_dir.kumoy.sprite import embedding_size_increase
        from plugin_dir.ui.project_save_handler import confirm_symbol_embedding

        layer, icon = self._project_with_icon(project, tmp_path)
        self._set_limit_above_current_size(
            monkeypatch, embedding_size_increase(project) - 1
        )

        confirm_symbol_embedding(project)

        assert ask.calls == 0
        assert ask.warnings == 1
        assert self._icon_path(layer) == icon

    def test_silent_when_already_over_the_limit(
        self, project, ask, tmp_path, monkeypatch
    ):
        """The size check that follows reports it: no second dialog."""
        from plugin_dir.ui.project_save_handler import confirm_symbol_embedding

        layer, icon = self._project_with_icon(project, tmp_path)
        self._set_limit_above_current_size(monkeypatch, -1)

        confirm_symbol_embedding(project)

        assert ask.calls == 0
        assert ask.warnings == 0
        assert self._icon_path(layer) == icon
