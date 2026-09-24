"""Tests for kumoy/local_cache/map.py

Verifies that get_cache_size sums sizes with the same matching rule as
clear(): any file whose name contains map_id.
"""

import types

import pytest


@pytest.mark.usefixtures("qgis_plugin_path")
class TestCacheSize:
    @pytest.fixture
    def cache(self, tmp_path, monkeypatch):
        from plugin_dir.kumoy.local_cache import map as map_cache

        cache_dir = tmp_path / "maps"
        cache_dir.mkdir()
        monkeypatch.setattr(map_cache, "get_cache_dir", lambda: str(cache_dir))
        return types.SimpleNamespace(mod=map_cache, cache_dir=cache_dir)

    def test_zero_when_not_cached(self, cache):
        assert cache.mod.get_cache_size("m-1") == 0

    def test_zero_when_cache_file_is_empty(self, cache):
        (cache.cache_dir / "m-1.qgs").write_bytes(b"")

        assert cache.mod.get_cache_size("m-1") == 0

    def test_sums_files_containing_map_id(self, cache):
        (cache.cache_dir / "m-1.qgs").write_bytes(b"x" * 100)
        (cache.cache_dir / "m-1_extra.dat").write_bytes(b"x" * 30)
        # Files of other maps are not counted
        (cache.cache_dir / "m-2.qgs").write_bytes(b"x" * 999)

        assert cache.mod.get_cache_size("m-1") == 130

    def test_total_zero_when_no_files(self, cache):
        assert cache.mod.get_total_cache_size() == 0

    def test_total_sums_all_files(self, cache):
        (cache.cache_dir / "m-1.qgs").write_bytes(b"x" * 100)
        (cache.cache_dir / "m-2.qgs").write_bytes(b"x" * 60)

        assert cache.mod.get_total_cache_size() == 160

    def test_clear_all_removes_files_and_subdirs(self, cache):
        (cache.cache_dir / "m-1.qgs").write_bytes(b"x" * 100)
        sub = cache.cache_dir / "sub"
        sub.mkdir()
        (sub / "nested.qgs").write_bytes(b"x" * 60)

        assert cache.mod.clear_all() is True
        assert list(cache.cache_dir.iterdir()) == []
        assert cache.mod.get_total_cache_size() == 0


@pytest.mark.usefixtures("qgis_plugin_path")
class TestReadProjectFile:
    @pytest.fixture
    def map_cache(self, tmp_path, monkeypatch):
        from plugin_dir.kumoy.local_cache import map as map_cache

        cache_dir = tmp_path / "maps"
        cache_dir.mkdir()
        monkeypatch.setattr(map_cache, "get_cache_dir", lambda: str(cache_dir))
        return map_cache

    def test_kumoy_layers_are_left_unresolved(self, map_cache, tmp_path):
        from .project_files import write_kumoy_point_project

        project = map_cache.read_project_file(str(write_kumoy_point_project(tmp_path)))

        (layer,) = project.mapLayers().values()
        assert layer.providerType() == "kumoy"
        assert not layer.isValid()
        assert layer.renderer() is not None

    def test_pinned_aspect_ratio_is_written_for_unresolved_layers(
        self, map_cache, tmp_path
    ):
        from .project_files import fixed_aspect_ratios, write_kumoy_point_project

        path = write_kumoy_point_project(tmp_path)
        assert fixed_aspect_ratios(path.read_text(encoding="utf-8")) == ["0"]

        qgisproject = map_cache.serialize_detached_project(
            map_cache.read_project_file(str(path))
        )

        assert fixed_aspect_ratios(qgisproject) == ["0.5"]
        assert "vector_id=v1" in qgisproject

    def test_local_paths_become_relative_to_cache_dir(self, map_cache, tmp_path):
        from qgis.core import (
            QgsCoordinateTransformContext,
            QgsProject,
            QgsVectorFileWriter,
            QgsVectorLayer,
        )

        data_dir = tmp_path / "src" / "data"
        data_dir.mkdir(parents=True)
        gpkg = str(data_dir / "points.gpkg")
        QgsVectorFileWriter.writeAsVectorFormatV3(
            QgsVectorLayer("Point?crs=EPSG:4326", "points", "memory"),
            gpkg,
            QgsCoordinateTransformContext(),
            QgsVectorFileWriter.SaveVectorOptions(),
        )
        project = QgsProject()
        project.addMapLayer(QgsVectorLayer(gpkg, "points", "ogr"))
        project_path = str(tmp_path / "src" / "project.qgz")
        project.write(project_path)

        qgisproject = map_cache.serialize_detached_project(
            map_cache.read_project_file(project_path)
        )

        assert "<datasource>../src/data/points.gpkg</datasource>" in qgisproject

    @staticmethod
    def _canvas_extent(qgisproject):
        import xml.etree.ElementTree as ET

        (canvas,) = [
            e
            for e in ET.fromstring(qgisproject).iter("mapcanvas")
            if e.get("name") == "theMapCanvas"
        ]
        extent = canvas.find("extent")
        return [float(extent.find(k).text) for k in ("xmin", "ymin", "xmax", "ymax")]

    def test_map_canvas_extent_is_kept(self, map_cache, tmp_path):
        from qgis.core import QgsCoordinateReferenceSystem, QgsProject

        path = tmp_path / "project.qgs"
        project = QgsProject()
        project.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        project.write(str(path))
        # As saved from QGIS, whose map canvas writes this element
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "</qgis>",
                '<mapcanvas name="theMapCanvas"><units>degrees</units><extent>'
                "<xmin>139</xmin><ymin>35</ymin><xmax>140</xmax><ymax>36</ymax>"
                "</extent><rotation>0</rotation></mapcanvas></qgis>",
            ),
            encoding="utf-8",
        )

        qgisproject = map_cache.serialize_detached_project(
            map_cache.read_project_file(str(path))
        )

        assert self._canvas_extent(qgisproject) == [139, 35, 140, 36]

    def test_default_view_extent_becomes_map_canvas_extent(self, map_cache, tmp_path):
        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsProject,
            QgsRectangle,
            QgsReferencedRectangle,
        )

        # A project built by a script has no map canvas to write <mapcanvas>
        project = QgsProject()
        project.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        project.viewSettings().setDefaultViewExtent(
            QgsReferencedRectangle(
                QgsRectangle(15473000, 4163000, 15585000, 4300000),
                QgsCoordinateReferenceSystem("EPSG:3857"),
            )
        )
        path = str(tmp_path / "project.qgs")
        project.write(path)

        qgisproject = map_cache.serialize_detached_project(
            map_cache.read_project_file(path)
        )

        xmin, ymin, xmax, ymax = self._canvas_extent(qgisproject)
        assert xmin == pytest.approx(139.0, abs=0.01)
        assert ymin == pytest.approx(34.9, abs=0.1)
        assert xmax == pytest.approx(140.0, abs=0.01)
        assert ymax == pytest.approx(35.9, abs=0.1)

    def test_unreadable_file_fails(self, map_cache, tmp_path):
        path = tmp_path / "broken.qgs"
        path.write_text("not a project", encoding="utf-8")

        with pytest.raises(RuntimeError):
            map_cache.read_project_file(str(path))
