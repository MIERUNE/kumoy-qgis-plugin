from pathlib import Path

import pytest
from qgis.core import (
    NULL,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QDate, QDateTime, QTime, QVariant


def _fields_with_values():
    fields = QgsFields()
    fields.append(QgsField("kumoy_id", QVariant.LongLong))
    fields.append(QgsField("integer_value", QVariant.LongLong))
    fields.append(QgsField("float_value", QVariant.Double))
    fields.append(QgsField("boolean_value", QVariant.Bool))
    fields.append(QgsField("string_value", QVariant.String))
    fields.append(QgsField("datetime_value", QVariant.DateTime))
    fields.append(QgsField("date_value", QVariant.Date))
    fields.append(QgsField("time_value", QVariant.Time))
    return fields


def _feature(fields, attributes, wkt=None):
    feature = QgsFeature(fields)
    feature.setAttributes(attributes)
    if wkt is not None:
        feature.setGeometry(QgsGeometry.fromWkt(wkt))
    feature.setValid(True)
    return feature


def _open_bytes(tmp_path: Path, payload: bytes, name="transfer.fgb"):
    path = tmp_path / name
    path.write_bytes(payload)
    layer = QgsVectorLayer(str(path), "transfer", "ogr")
    assert layer.isValid()
    return layer


@pytest.mark.usefixtures("qgis_plugin_path")
class TestFlatGeobufWriter:
    def test_round_trips_values_nulls_zm_and_dates(self, tmp_path):
        from plugin_dir.kumoy.api.flatgeobuf import features_to_flatgeobuf

        fields = _fields_with_values()
        features = [
            _feature(
                fields,
                [
                    10,
                    9_007_199_254_740_991,
                    3.25,
                    True,
                    "日本語",
                    QDateTime(QDate(2026, 2, 4), QTime(10, 29, 41, 859)),
                    QDate(2026, 2, 4),
                    QTime(10, 29, 41, 859),
                ],
                "POINT ZM (139 35 10 20)",
            ),
            _feature(fields, [11, NULL, 8.5, NULL, NULL, NULL, NULL, NULL]),
        ]

        layer = _open_bytes(tmp_path, features_to_flatgeobuf(features))
        assert layer.fields().names() == [
            "integer_value",
            "float_value",
            "boolean_value",
            "string_value",
            "datetime_value",
            "date_value",
            "time_value",
        ]
        assert layer.fields().field("boolean_value").type() == QVariant.Bool
        assert layer.fields().field("datetime_value").type() == QVariant.String

        rows = list(layer.getFeatures())
        assert rows[0]["integer_value"] == 9_007_199_254_740_991
        assert rows[0]["boolean_value"] is True
        assert rows[0]["datetime_value"] == "2026-02-04T10:29:41.859"
        assert rows[0]["date_value"] == "2026-02-04"
        assert rows[0]["time_value"] == "10:29:41.859"
        assert QgsWkbTypes.hasZ(rows[0].geometry().wkbType())
        assert QgsWkbTypes.hasM(rows[0].geometry().wkbType())
        point = rows[0].geometry().constGet()
        assert point.z() == pytest.approx(10)
        assert point.m() == pytest.approx(20)
        assert rows[1].geometry().isEmpty()
        assert rows[1]["integer_value"] == NULL
        assert rows[1]["boolean_value"] == NULL
        del layer

    @pytest.mark.parametrize(
        ("wkt", "flat_type"),
        [
            ("LINESTRING Z (139 35 1, 140 36 2)", QgsWkbTypes.LineString),
            (
                "POLYGON Z ((139 35 1, 140 35 2, 140 36 3, 139 35 1))",
                QgsWkbTypes.Polygon,
            ),
        ],
    )
    def test_writes_line_and_polygon_z(self, tmp_path, wkt, flat_type):
        from plugin_dir.kumoy.api.flatgeobuf import features_to_flatgeobuf

        fields = QgsFields()
        fields.append(QgsField("name", QVariant.String))
        feature = _feature(fields, ["shape"], wkt)

        layer = _open_bytes(tmp_path, features_to_flatgeobuf([feature]))
        output = next(layer.getFeatures())
        assert QgsWkbTypes.flatType(output.geometry().wkbType()) == flat_type
        assert QgsWkbTypes.hasZ(output.geometry().wkbType())
        del layer

    def test_geometry_only_contains_kumoy_id(self, tmp_path):
        from plugin_dir.kumoy.api.flatgeobuf import features_to_flatgeobuf

        fields = QgsFields()
        fields.append(QgsField("kumoy_id", QVariant.LongLong))
        fields.append(QgsField("ignored", QVariant.String))
        features = [
            _feature(fields, [101, "a"], "POINT (139 35)"),
            _feature(fields, [202, "b"], "POINT (140 36)"),
        ]

        layer = _open_bytes(
            tmp_path,
            features_to_flatgeobuf(features, geometry_only=True),
            "geometry-only.fgb",
        )
        assert layer.fields().names() == ["kumoy_id"]
        assert [feature["kumoy_id"] for feature in layer.getFeatures()] == [101, 202]
        del layer

    def test_legacy_json_path_uses_same_normalization(self, monkeypatch):
        from plugin_dir.kumoy.api import qgis_vector

        fields = _fields_with_values()
        feature = _feature(
            fields,
            [
                10,
                1,
                2.5,
                True,
                NULL,
                QDateTime(QDate(2026, 2, 4), QTime(10, 29, 41, 859)),
                QDate(2026, 2, 4),
                QTime(10, 29, 41, 859),
            ],
            "POINT (139 35)",
        )
        calls = []
        monkeypatch.setattr(
            qgis_vector.ApiClient,
            "post",
            staticmethod(lambda endpoint, body: calls.append((endpoint, body))),
        )

        qgis_vector._add_features_v1("vector-id", [feature])

        properties = calls[0][1]["features"][0]["properties"]
        assert "kumoy_id" not in properties
        assert properties["string_value"] is None
        assert properties["datetime_value"] == "2026-02-04T10:29:41.859"
