"""kumoy:uploadvector: feature preparation, batching and the upload flow."""

import base64
import math
from types import SimpleNamespace

import pytest
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QDate, QVariant


@pytest.fixture
def algorithm(qgis_plugin_path):
    from plugin_dir.processing.vector.upload import algorithm

    return algorithm


def _from_wkb(encoded):
    geometry = QgsGeometry()
    geometry.fromWkb(base64.b64decode(encoded))
    return geometry


def _layer(uri, rows):
    """Memory layer from (wkt, attributes) rows."""
    layer = QgsVectorLayer(uri, "roads", "memory")
    assert layer.isValid()
    features = []
    for wkt, attributes in rows:
        feature = QgsFeature(layer.fields())
        if wkt is not None:
            feature.setGeometry(QgsGeometry.fromWkt(wkt))
        feature.setAttributes(attributes)
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    return layer


@pytest.mark.parametrize(
    "uri, expected",
    [
        ("Point", "POINT"),
        ("MultiPointZ", "POINT"),
        ("PointM", "POINT"),
        ("LineString", "LINESTRING"),
        ("MultiLineString", "LINESTRING"),
        ("PolygonZ", "POLYGON"),
        ("MultiPolygon", "POLYGON"),
        ("None", None),
    ],
)
def test_geometry_type(algorithm, uri, expected):
    layer = QgsVectorLayer(f"{uri}?crs=EPSG:4326", "t", "memory")
    assert algorithm._get_geometry_type(layer) == expected


@pytest.mark.parametrize(
    "field_type, expected",
    [
        (QVariant.String, "string"),
        (QVariant.Int, "integer"),
        (QVariant.LongLong, "integer"),
        (QVariant.UInt, "integer"),
        (QVariant.Double, "float"),
        (QVariant.Bool, "boolean"),
        (QVariant.Date, "string"),
        (QVariant.Map, "string"),
    ],
)
def test_column_type(algorithm, field_type, expected):
    from qgis.core import QgsField

    assert algorithm._column_type(QgsField("f", field_type).type()) == expected


class TestJsonValue:
    def test_null(self, algorithm):
        assert algorithm._to_json_value(QVariant(), "string") is None
        assert algorithm._to_json_value(None, "integer") is None

    def test_non_finite_float_becomes_null(self, algorithm):
        # json.dumps would write NaN, which the server cannot parse
        assert algorithm._to_json_value(math.nan, "float") is None
        assert algorithm._to_json_value(math.inf, "float") is None
        assert algorithm._to_json_value(1.5, "float") == 1.5

    def test_text_is_cut_to_255_utf16_units(self, algorithm):
        assert algorithm._to_json_value("a" * 300, "string") == "a" * 255
        # The server counts an emoji as two
        assert algorithm._to_json_value("😀" * 200, "string") == "😀" * 127

    def test_values_without_kumoy_type_become_text(self, algorithm):
        assert algorithm._to_json_value(QDate(2026, 2, 4), "string") == "2026-02-04"
        assert algorithm._to_json_value({"a": [1]}, "string") == '{"a": [1]}'
        assert algorithm._to_json_value(12, "string") == "12"


class TestPrepareGeometry:
    def _prepare(self, algorithm, wkt, geometry_type, transform=None):
        return [
            g.asWkt(3)
            for g in algorithm._prepare_geometry(
                QgsGeometry.fromWkt(wkt), geometry_type, transform
            )
        ]

    def test_multipart_z_becomes_2d_single_parts(self, algorithm):
        parts = self._prepare(
            algorithm,
            "MultiPointZ((1 2 3),(4 5 6))",
            Qgis.GeometryType.Point,
        )
        assert parts == ["Point (1 2)", "Point (4 5)"]

    def test_invalid_polygon_is_repaired(self, algorithm):
        # Bow tie: makeValid splits it into two triangles
        parts = self._prepare(
            algorithm,
            "Polygon((0 0, 2 2, 2 0, 0 2, 0 0))",
            Qgis.GeometryType.Polygon,
        )
        assert len(parts) == 2
        assert all(p.startswith("Polygon") for p in parts)

    @pytest.mark.parametrize(
        "wkt",
        ["Point EMPTY", "LineString(0 0, 1 1)", "Point(nan 1)"],
    )
    def test_unusable_geometries_are_skipped(self, algorithm, wkt):
        assert self._prepare(algorithm, wkt, Qgis.GeometryType.Point) == []

    def test_reprojects(self, algorithm):
        transform = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:3857"),
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsProject.instance(),
        )
        (part,) = algorithm._prepare_geometry(
            QgsGeometry.fromWkt("Point(15584728 4257206)"),
            Qgis.GeometryType.Point,
            transform,
        )
        assert part.asPoint().x() == pytest.approx(140.0, abs=0.01)
        assert part.asPoint().y() == pytest.approx(35.69, abs=0.01)


def test_batches_respect_count_and_size(algorithm, monkeypatch):
    monkeypatch.setattr(algorithm, "MAX_ITEMS_PER_REQUEST", 3)
    monkeypatch.setattr(algorithm, "_MAX_BATCH_WKB_LENGTH", 10)
    rows = [{"kumoy_wkb": "x" * n} for n in (1, 1, 1, 1, 6, 6, 20, 1)]

    sizes = [[len(r["kumoy_wkb"]) for r in b] for b in algorithm._batches(iter(rows))]

    # Count limit, size limit, and an oversized item goes alone
    assert sizes == [[1, 1, 1], [1, 6], [6], [20], [1]]


class TestNormalizeColumns:
    def test_reserved_and_selected_fields(self, algorithm):
        layer = _layer(
            "Point?crs=EPSG:4326&field=kumoy_id:integer&field=name:string"
            "&field=%20name%20:string&field=other:string",
            [],
        )
        feedback = QgsProcessingFeedback()

        columns = algorithm._build_columns(
            layer.fields(), {"kumoy_id", "name", " name "}, feedback
        )

        assert [(c.index, c.name) for c in columns] == [(1, "name"), (2, "name_1")]


class FakeApi:
    """Records the calls of the upload flow."""

    def __init__(self, monkeypatch, api, plan=None, fail_on_batch=None):
        self.calls = []
        self.batches = []
        self.fail_on_batch = fail_on_batch
        plan = plan or {}
        organization = SimpleNamespace(
            usage=SimpleNamespace(vectors=0, rasters=0, usedStorageUnits=0),
            availableStorageUnits=100,
            planSettings=SimpleNamespace(
                maxVectors=plan.get("maxVectors", 10),
                maxRasters=10,
                maxVectorFeatures=plan.get("maxVectorFeatures", 1000),
                maxVectorAttributes=plan.get("maxVectorAttributes", 10),
            ),
        )
        project = SimpleNamespace(
            role=plan.get("role", "ADMIN"),
            team=SimpleNamespace(organizationId="o1"),
        )
        monkeypatch.setattr(api.project, "get_project", lambda _: project)
        monkeypatch.setattr(
            api.organization, "get_organization", lambda _: organization
        )
        monkeypatch.setattr(api.vector, "create_vector", self.create_vector)
        monkeypatch.setattr(api.vector, "delete_vector", self.delete_vector)
        monkeypatch.setattr(api.qgis_vector, "add_attributes", self.add_attributes)
        monkeypatch.setattr(api.qgis_vector, "add_features", self.add_features)

    def create_vector(self, project_id, name, type):
        self.calls.append(("create", project_id, name, type))
        return "v1"

    def delete_vector(self, vector_id):
        self.calls.append(("delete", vector_id))

    def add_attributes(self, vector_id, attributes):
        self.calls.append(("attributes", attributes))

    def add_features(self, vector_id, features):
        if self.fail_on_batch == len(self.batches):
            raise self.error
        self.batches.append(features)

    error = Exception("server failed")


@pytest.mark.usefixtures("qgis_plugin_path")
class TestUploadFlow:
    @pytest.fixture
    def api(self, monkeypatch):
        from plugin_dir.kumoy import api, session

        monkeypatch.setattr(session, "_token", "token")
        return api

    def _run(self, algorithm, layer, feedback=None, **parameters):
        alg = algorithm.UploadVectorAlgorithm()
        alg.initAlgorithm()
        return alg.processAlgorithm(
            {"INPUT": layer, "PROJECT_ID": "p1", **parameters},
            QgsProcessingContext(),
            feedback or QgsProcessingFeedback(),
        )

    def test_uploads_2d_single_parts_in_wgs84(self, algorithm, api, monkeypatch):
        fake = FakeApi(monkeypatch, api)
        layer = _layer(
            "MultiPointZ?crs=EPSG:3857&field=name:string&field=n:integer",
            [
                ("MultiPointZ((15584728 4257206 1),(0 0 1))", ["a", 1]),
                (None, ["no geometry", 2]),
            ],
        )

        result = self._run(algorithm, layer)

        assert result == {"VECTOR_ID": "v1"}
        assert fake.calls == [
            ("create", "p1", "roads", "POINT"),
            (
                "attributes",
                [{"name": "name", "type": "string"}, {"name": "n", "type": "integer"}],
            ),
        ]
        (batch,) = fake.batches
        assert [f["properties"] for f in batch] == [{"name": "a", "n": 1}] * 2
        points = [_from_wkb(f["kumoy_wkb"]) for f in batch]
        assert [p.wkbType() for p in points] == [Qgis.WkbType.Point] * 2
        assert points[0].asPoint().x() == pytest.approx(140.0, abs=0.01)

    def test_selected_fields_and_name(self, algorithm, api, monkeypatch):
        fake = FakeApi(monkeypatch, api)
        layer = _layer(
            "Point?crs=EPSG:4326&field=a:string&field=b:string",
            [("Point(1 1)", ["x", "y"])],
        )

        self._run(algorithm, layer, SELECTED_FIELDS=["b"], VECTOR_NAME="mine")

        assert fake.calls[0] == ("create", "p1", "mine", "POINT")
        assert fake.batches[0][0]["properties"] == {"b": "y"}

    def test_nothing_is_created_without_valid_features(
        self, algorithm, api, monkeypatch
    ):
        fake = FakeApi(monkeypatch, api)
        layer = _layer("Point?crs=EPSG:4326", [(None, [])])

        with pytest.raises(QgsProcessingException, match="No features remain"):
            self._run(algorithm, layer)
        assert fake.calls == []

    @pytest.mark.parametrize(
        "plan, message",
        [
            ({"role": "MEMBER"}, "Editor role"),
            ({"maxVectors": 0}, "limit of 0 vectors"),
            ({"maxVectorFeatures": 1}, "up to 1 features"),
            ({"maxVectorAttributes": 0}, "up to 0 attributes"),
        ],
    )
    def test_limits_are_checked_before_creating(
        self, algorithm, api, monkeypatch, plan, message
    ):
        fake = FakeApi(monkeypatch, api, plan=plan)
        layer = _layer(
            "Point?crs=EPSG:4326&field=a:string",
            [("Point(1 1)", ["x"]), ("Point(2 2)", ["y"])],
        )

        with pytest.raises(QgsProcessingException, match=message):
            self._run(algorithm, layer)
        assert fake.calls == []

    def test_failure_deletes_the_vector(self, algorithm, api, monkeypatch):
        fake = FakeApi(monkeypatch, api, fail_on_batch=0)
        fake.error = api.error.QuotaExceededError("Quota", "storage")
        layer = _layer("Point?crs=EPSG:4326", [("Point(1 1)", [])])

        with pytest.raises(QgsProcessingException, match="limit of its plan"):
            self._run(algorithm, layer)
        assert fake.calls[-1] == ("delete", "v1")

    def test_cancel_deletes_the_vector_and_returns_nothing(
        self, algorithm, api, monkeypatch
    ):
        fake = FakeApi(monkeypatch, api)
        monkeypatch.setattr(algorithm, "MAX_ITEMS_PER_REQUEST", 1)
        feedback = QgsProcessingFeedback()
        # Cancel once the first batch is sent
        monkeypatch.setattr(
            api.qgis_vector,
            "add_features",
            lambda *_: feedback.cancel(),
        )
        layer = _layer("Point?crs=EPSG:4326", [("Point(1 1)", []), ("Point(2 2)", [])])

        assert self._run(algorithm, layer, feedback) == {}
        assert fake.calls[-1] == ("delete", "v1")


@pytest.mark.usefixtures("qgis_plugin_path", "qgis_processing")
def test_layer_conversion_runs_the_registered_tool_in_a_worker(monkeypatch):
    """_upload_vector runs 'kumoy:uploadvector' by id off the main thread."""
    from qgis.core import QgsApplication
    from qgis.PyQt.QtCore import QEventLoop, QThread

    from plugin_dir.kumoy import api, session
    from plugin_dir.processing.provider import KumoyProcessingProvider
    from plugin_dir.ui.layers import _upload_vector

    registry = QgsApplication.processingRegistry()
    if registry.providerById("kumoy") is None:
        registry.addProvider(KumoyProcessingProvider())
    monkeypatch.setattr(session, "_token", "token")
    fake = FakeApi(monkeypatch, api)
    threads = []
    original = fake.add_features
    fake_add = lambda *a: threads.append(QThread.currentThread()) or original(*a)  # noqa: E731
    monkeypatch.setattr(api.qgis_vector, "add_features", fake_add)
    monkeypatch.setattr(_upload_vector.vector_layer, "create_vector_layer", lambda v: v)
    layer = _layer("Point?crs=EPSG:4326", [("Point(1 1)", [])])
    loop = QEventLoop()
    outcome = []

    def done(value):
        outcome.append(value)
        loop.quit()

    _upload_vector.upload(layer, "p1", "name", None, done, done)
    loop.exec()

    (vector,) = outcome
    assert (vector.id, vector.name, vector.type, vector.projectId) == (
        "v1",
        "name",
        "POINT",
        "p1",
    )
    assert threads and threads[0] != QThread.currentThread()
    assert fake.calls[0] == ("create", "p1", "name", "POINT")
