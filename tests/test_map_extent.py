"""Tests for kumoy/map_project.py (serializing projects for Kumoy maps).

QgsVectorLayer asks its provider for the extent once and caches it, and write()
omits <extent> entirely when it is null. A Kumoy layer can return null while
the server has no extent yet, so map_project.prepare() recomputes it.
"""

import re

import pytest


def _extent_block(qgs_str: str, layer_name: str):
    """Return the <extent> block of the named maplayer, or None if absent."""
    for m in re.finditer(r"<maplayer.*?</maplayer>", qgs_str, re.S):
        block = m.group(0)
        name = re.search(r"<layername>(.*?)</layername>", block)
        if name is None or name.group(1) != layer_name:
            continue
        extent = re.search(r"<extent>.*?</extent>", block, re.S)
        return extent.group(0) if extent else None
    raise AssertionError(f"maplayer '{layer_name}' not found in project")


def _make_tif(path: str):
    from osgeo import gdal, osr

    ds = gdal.GetDriverByName("GTiff").Create(path, 8, 8, 1, gdal.GDT_Byte)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    ds.SetGeoTransform([10.0, 0.1, 0, 50.0, 0, -0.1])
    ds.Close()


@pytest.fixture
def map_project(qgis_plugin_path):
    from plugin_dir.kumoy import map_project

    return map_project


@pytest.fixture
def kumoy_layer(fake_kumoy_provider):
    from qgis.core import QgsProject, QgsVectorLayer

    from plugin_dir.kumoy.constants import DATA_PROVIDER_KEY

    project = QgsProject()
    layer = QgsVectorLayer(
        "project_id=p-1;vector_id=v-1;vector_name=points;vector_type=POINT;",
        "points",
        DATA_PROVIDER_KEY,
    )
    assert layer.isValid()
    project.addMapLayer(layer)
    # The project owns the layer: keep it alive for the test
    layer.owner = project
    return layer


def _serialize(map_project, layer):
    return map_project.serialize_detached(layer.owner)


class TestExtent:
    def test_extent_written(self, map_project, kumoy_layer, fake_kumoy_provider):
        from qgis.core import QgsRectangle

        fake_kumoy_provider.extent = QgsRectangle(139.0, 35.0, 140.0, 36.0)
        fake_kumoy_provider.feature_count = 3

        block = _extent_block(_serialize(map_project, kumoy_layer), "points")
        assert block is not None
        assert "<xmin>139</xmin>" in block

    def test_extent_recovered_after_null_was_cached(
        self, map_project, kumoy_layer, fake_kumoy_provider
    ):
        from qgis.core import QgsRectangle

        assert kumoy_layer.extent().isNull()  # null is cached here

        fake_kumoy_provider.extent = QgsRectangle(139.0, 35.0, 140.0, 36.0)
        fake_kumoy_provider.feature_count = 3

        block = _extent_block(_serialize(map_project, kumoy_layer), "points")
        assert "<xmin>139</xmin>" in block

    def test_extent_written_without_local_cache(
        self, map_project, kumoy_layer, fake_kumoy_provider
    ):
        """updateExtents() does nothing while featureCount() is 0."""
        from qgis.core import QgsRectangle

        assert kumoy_layer.extent().isNull()

        fake_kumoy_provider.extent = QgsRectangle(139.0, 35.0, 140.0, 36.0)
        fake_kumoy_provider.feature_count = 0

        block = _extent_block(_serialize(map_project, kumoy_layer), "points")
        assert "<xmin>139</xmin>" in block

    def test_null_provider_extent_left_alone(self, map_project, kumoy_layer):
        assert _extent_block(_serialize(map_project, kumoy_layer), "points") is None

    def test_stale_extent_updated(self, map_project, kumoy_layer, fake_kumoy_provider):
        from qgis.core import QgsRectangle

        fake_kumoy_provider.extent = QgsRectangle(0.0, 0.0, 1.0, 1.0)
        fake_kumoy_provider.feature_count = 1
        assert not kumoy_layer.extent().isNull()

        fake_kumoy_provider.extent = QgsRectangle(139.0, 35.0, 140.0, 36.0)

        block = _extent_block(_serialize(map_project, kumoy_layer), "points")
        assert "<xmin>139</xmin>" in block

    def test_raster_layer_is_left_alone(
        self, map_project, kumoy_layer, fake_kumoy_provider, tmp_path
    ):
        """QgsRasterLayer has no updateExtents()."""
        from qgis.core import QgsRasterLayer

        path = str(tmp_path / "dem.tif")
        _make_tif(path)
        kumoy_layer.owner.addMapLayer(QgsRasterLayer(path, "dem"))

        assert _extent_block(_serialize(map_project, kumoy_layer), "dem") is not None


class TestSerializeDetached:
    def test_layer_tree_keeps_provider_key(
        self, map_project, tmp_path, fake_kumoy_provider
    ):
        from .project_files import write_kumoy_point_project

        qgisproject = map_project.serialize_detached(
            map_project.read_project_file(str(write_kumoy_point_project(tmp_path)))
        )

        # The web layer tree derives geometry types of legends from this key
        assert re.findall(
            r'<layer-tree-layer[^>]*providerKey="([^"]*)"', qgisproject
        ) == ["kumoy"]

    def test_pinned_aspect_ratio_is_written(
        self, map_project, tmp_path, fake_kumoy_provider
    ):
        from .project_files import fixed_aspect_ratios, write_kumoy_point_project

        path = write_kumoy_point_project(tmp_path)
        assert fixed_aspect_ratios(path.read_text(encoding="utf-8")) == ["0"]

        qgisproject = map_project.serialize_detached(
            map_project.read_project_file(str(path))
        )

        assert fixed_aspect_ratios(qgisproject) == ["0.5"]
        assert "vector_id=v1" in qgisproject

    def test_local_paths_are_absolute(self, map_project, tmp_path):
        """A map has no directory that relative paths could refer to."""
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

        qgisproject = map_project.serialize_detached(
            map_project.read_project_file(project_path)
        )

        assert f"<datasource>{gpkg}</datasource>" in qgisproject

    def test_unreadable_file_fails(self, map_project, tmp_path):
        path = tmp_path / "broken.qgs"
        path.write_text("not a project", encoding="utf-8")

        with pytest.raises(RuntimeError):
            map_project.read_project_file(str(path))


class TestHelpers:
    def test_uri_roundtrip(self, map_project):
        assert map_project.map_id_from_uri(map_project.map_uri("m-1")) == "m-1"

    @pytest.mark.parametrize("uri", ["", "kumoy:", "/tmp/kumoy:m-1.qgs", "m-1"])
    def test_not_a_map_uri(self, map_project, uri):
        assert map_project.map_id_from_uri(uri) is None

    def test_size_error(self, map_project, monkeypatch):
        monkeypatch.setattr(map_project, "MAX_QGISPROJECT_LENGTH", 5)

        assert map_project.size_error("12345") is None
        assert "6" in map_project.size_error("123456")

    def test_foreign_kumoy_layers(self, map_project, fake_kumoy_provider):
        from qgis.core import QgsProject, QgsVectorLayer

        from plugin_dir.kumoy.constants import DATA_PROVIDER_KEY

        project = QgsProject()
        for name, project_id in (("mine", "p-1"), ("theirs", "p-2")):
            project.addMapLayer(
                QgsVectorLayer(
                    f"project_id={project_id};vector_id={name};vector_name={name};"
                    "vector_type=POINT;",
                    name,
                    DATA_PROVIDER_KEY,
                )
            )
        project.addMapLayer(QgsVectorLayer("Point?crs=EPSG:4326", "local", "memory"))

        assert map_project.foreign_kumoy_layers(project, "p-1") == ["theirs"]
