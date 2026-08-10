import hashlib
from pathlib import Path

import pytest
from qgis.core import (
    NULL,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "flatgeobuf"
FIXTURE_SHA256 = "742a3f8b34ca30b331d8b2b5f5a648948faeef14893efda5aca7b5fc3d7abbd2"


def _expected_fields():
    fields = QgsFields()
    fields.append(QgsField("kumoy_id", QVariant.LongLong))
    fields.append(QgsField("integer_value", QVariant.LongLong))
    fields.append(QgsField("float_value", QVariant.Double))
    fields.append(QgsField("boolean_value", QVariant.Bool))
    fields.append(QgsField("string_value", QVariant.String))
    return fields


def _write_json_equivalent(path: str):
    fields = _expected_fields()
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.layerOptions = ["FID=kumoy_id"]
    options.driverName = "GPKG"
    options.fileEncoding = "UTF-8"
    writer = QgsVectorFileWriter.create(
        path,
        fields,
        QgsWkbTypes.PointZM,
        QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsProject.instance().transformContext(),
        options,
    )
    assert writer.hasError() == QgsVectorFileWriter.NoError

    rows = [
        (1, 42, 3.25, True, "first", "POINT ZM (139 35 10 20)"),
        (2, None, 8.5, None, "partial", None),
        (
            3,
            9_007_199_254_740_991,
            -2.5,
            False,
            "日本語",
            "POINT ZM (140 36 -5 7)",
        ),
    ]
    for row in rows:
        feature = QgsFeature(fields)
        feature.setId(row[0])
        feature.setAttributes(list(row[:5]))
        if row[5] is not None:
            feature.setGeometry(QgsGeometry.fromWkt(row[5]))
        feature.setValid(True)
        assert writer.addFeature(feature)
    del writer


def _value(value):
    return None if value == NULL else value


def _snapshot(path: str):
    layer = QgsVectorLayer(path, "cache", "ogr")
    assert layer.isValid()
    field_types = [(field.name(), field.type()) for field in layer.fields()]
    features = []
    for feature in layer.getFeatures():
        geometry = feature.geometry()
        features.append(
            (
                feature.id(),
                tuple(_value(feature[name]) for name in layer.fields().names()),
                None if geometry.isNull() else bytes(geometry.asWkb()),
            )
        )
    del layer
    return field_types, features


@pytest.mark.usefixtures("qgis_plugin_path")
class TestFlatGeobufCacheImport:
    @pytest.mark.parametrize(
        "fixture_name", ["postgis-single.fgb", "postgis-chunked.fgb"]
    )
    def test_imports_real_postgis_fixture(self, tmp_path, fixture_name):
        from plugin_dir.kumoy.local_cache.flatgeobuf import (
            import_flatgeobuf_to_geopackage,
        )

        fixture = FIXTURE_DIR / fixture_name
        assert hashlib.sha256(fixture.read_bytes()).hexdigest() == FIXTURE_SHA256
        output = tmp_path / f"{fixture_name}.gpkg"
        progress = []

        import_flatgeobuf_to_geopackage(
            str(fixture), str(output), progress_callback=progress.append
        )

        layer = QgsVectorLayer(str(output), "cache", "ogr")
        assert layer.isValid()
        assert layer.crs().authid() == "EPSG:4326"
        assert layer.featureCount() == 3
        assert layer.fields().field("boolean_value").type() == QVariant.Bool

        features = {feature.id(): feature for feature in layer.getFeatures()}
        assert set(features) == {1, 2, 3}
        assert all(feature["kumoy_id"] == feature.id() for feature in features.values())

        first_point = features[1].geometry().constGet()
        assert QgsWkbTypes.hasZ(features[1].geometry().wkbType())
        assert QgsWkbTypes.hasM(features[1].geometry().wkbType())
        assert first_point.z() == pytest.approx(10)
        assert first_point.m() == pytest.approx(20)

        assert features[2].geometry().isEmpty()
        assert _value(features[2]["integer_value"]) is None
        assert _value(features[2]["boolean_value"]) is None
        assert features[2]["float_value"] == pytest.approx(8.5)
        assert features[3]["integer_value"] == 9_007_199_254_740_991
        assert features[3]["string_value"] == "日本語"
        assert progress == [1, 2, 3]
        del layer

    def test_matches_existing_json_cache_shape(self, tmp_path):
        from plugin_dir.kumoy.local_cache.flatgeobuf import (
            import_flatgeobuf_to_geopackage,
        )

        fgb_cache = tmp_path / "fgb.gpkg"
        json_cache = tmp_path / "json.gpkg"
        import_flatgeobuf_to_geopackage(
            str(FIXTURE_DIR / "postgis-chunked.fgb"), str(fgb_cache)
        )
        _write_json_equivalent(str(json_cache))

        assert _snapshot(str(fgb_cache)) == _snapshot(str(json_cache))
