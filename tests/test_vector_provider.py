"""Kumoy vector provider: cache-first open, background sync, editing.

The API is replaced by an in-memory FakeServer patched onto
kumoy.api.qgis_vector / kumoy.api.vector.
"""

import base64
import threading
import time
import types
from datetime import datetime, timezone

import pytest
from qgis.core import (
    NULL,
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsProviderMetadata,
    QgsProviderRegistry,
    QgsVectorLayer,
    QgsVectorLayerCache,
)
from qgis.PyQt.QtCore import QMetaType, Qt

# The shared conftest may register a stub under "kumoy"; registration is once
# per session, so the real provider gets its own key here
TEST_KEY = "kumoy_test"
ADD = Qgis.VectorProviderCapability.AddFeatures
VID = "v1"


class FakeServer:
    def __init__(self, columns=(("name", "string"),), type_="POINT", role="ADMIN"):
        from plugin_dir.kumoy.api.models import Column

        self.columns = [Column(n, t) for n, t in columns]
        self.type = type_
        self.role = role
        self.rows = {}  # id -> {"kumoy_wkb": bytes, "properties": {...}}
        self.next_id = 1
        self.calls = []
        self.error = None  # raised by every call when set
        self.diff_error = None
        self.features_error_after = None  # raise on pages after this many
        self.date = datetime(2026, 11, 17, 12, 0, 0, tzinfo=timezone.utc)
        self.pending_diff = ([], [])
        self.gate = None  # threading.Event: hold syncs until set

    def add_row(self, x, **props):
        fid = self.next_id
        self.next_id += 1
        wkb = bytes(QgsGeometry.fromPointXY(QgsPointXY(x, 0)).asWkb())
        self.rows[fid] = {"kumoy_wkb": wkb, "properties": props}
        return fid

    def _call(self, name, *args):
        self.calls.append((name, args))
        if self.error is not None:
            # A reused exception collects the frames of every raise, keeping
            # providers alive past QGIS shutdown (crash in the final GC)
            raise self.error.with_traceback(None)

    def names(self):
        return [c[0] for c in self.calls]

    def detail(self):
        from plugin_dir.kumoy.api.models import VectorDetail

        return VectorDetail(
            id=VID,
            name="vec",
            type=self.type,
            projectId="p1",
            role=self.role,
            columns=list(self.columns),
            count=len(self.rows),
            extent=[0.0, 0.0, 10.0, 10.0],
        )

    def _out(self, fid):
        row = self.rows[fid]
        props = {c.name: row["properties"].get(c.name) for c in self.columns}
        return {"kumoy_id": fid, "kumoy_wkb": row["kumoy_wkb"], "properties": props}

    # --- patched API ---
    def get_vector(self, vector_id):
        self._call("get_vector", vector_id)
        return self.detail()

    def get_vector_and_server_time(self, vector_id):
        if self.gate is not None:
            self.gate.wait(10)
        self._call("get_vector_and_server_time", vector_id)
        return self.detail(), self.date

    def get_features(self, vector_id, after_id=None):
        from plugin_dir.kumoy.provider import dataprovider

        self._call("get_features", after_id)
        pages = len([c for c in self.calls if c[0] == "get_features"])
        if self.features_error_after is not None and pages > self.features_error_after:
            raise RuntimeError("connection lost")
        ids = sorted(i for i in self.rows if after_id is None or i > after_id)
        return [self._out(i) for i in ids[: dataprovider.FEATURES_PAGE_SIZE]]

    def get_diff(self, vector_id, last_updated):
        from plugin_dir.kumoy.api.qgis_vector import Diff

        self._call("get_diff", last_updated)
        if self.diff_error is not None:
            raise self.diff_error.with_traceback(None)
        updated, deleted = self.pending_diff
        self.pending_diff = ([], [])
        return Diff([self._out(i) for i in updated], list(deleted))

    def add_features(self, vector_id, features):
        self._call("add_features", features)
        ids = []
        for f in features:
            fid = self.next_id
            self.next_id += 1
            self.rows[fid] = {
                "kumoy_wkb": base64.b64decode(f["kumoy_wkb"]),
                "properties": f["properties"],
            }
            ids.append(fid)
        return ids

    def change_attribute_values(self, vector_id, items):
        self._call("change_attribute_values", items)
        for item in items:
            self.rows[item["kumoy_id"]]["properties"].update(item["properties"])

    def change_geometry_values(self, vector_id, items):
        self._call("change_geometry_values", items)
        for item in items:
            wkb = base64.b64decode(item["kumoy_wkb"])
            self.rows[item["kumoy_id"]]["kumoy_wkb"] = wkb

    def delete_features(self, vector_id, ids):
        self._call("delete_features", ids)
        for i in ids:
            self.rows.pop(i, None)

    def add_attributes(self, vector_id, attributes):
        from plugin_dir.kumoy.api.models import Column

        self._call("add_attributes", attributes)
        self.columns += [Column(a["name"], a["type"]) for a in attributes]

    def delete_attributes(self, vector_id, names):
        self._call("delete_attributes", names)
        self.columns = [c for c in self.columns if c.name not in names]


@pytest.fixture(scope="session")
def _registered(qgis_app, qgis_plugin_path):
    from plugin_dir.kumoy.provider.dataprovider import KumoyDataProvider

    QgsProviderRegistry.instance().registerProvider(
        QgsProviderMetadata(TEST_KEY, "test", KumoyDataProvider.createProvider)
    )


@pytest.fixture
def env(_registered, qgis_app, tmp_path, monkeypatch):
    from plugin_dir.kumoy import api, session
    from plugin_dir.kumoy.local_cache import vector as cache
    from plugin_dir.kumoy.provider import dataprovider

    root = tmp_path / "vectors"
    root.mkdir()
    monkeypatch.setattr(cache, "_root_dir", lambda: str(root))
    monkeypatch.setattr(session, "is_logged_in", lambda: True)
    server = FakeServer()
    for name in (
        "get_vector_and_server_time",
        "get_features",
        "get_diff",
        "add_features",
        "change_attribute_values",
        "change_geometry_values",
        "delete_features",
        "add_attributes",
        "delete_attributes",
    ):
        monkeypatch.setattr(api.qgis_vector, name, getattr(server, name))
    monkeypatch.setattr(api.vector, "get_vector", server.get_vector)

    events = []
    ev = dataprovider.sync_events
    handlers = [
        (ev.sync_started, lambda v: events.append(("started", v))),
        (ev.sync_finished, lambda v: events.append(("finished", v))),
        (ev.sync_failed, lambda v, m, e: events.append(("failed", v, m, e))),
    ]
    for signal, handler in handlers:
        signal.connect(handler)
    layers = []

    def open_layer(subset=""):
        uri = f"project_id=p1;vector_id={VID};vector_name=vec;vector_type=POINT;"
        if subset:
            uri += f"subset={subset}"
        layer = QgsVectorLayer(uri, "vec", TEST_KEY)
        layers.append(layer)
        QgsProject.instance().addMapLayer(layer)
        return layer

    def wait():
        deadline = time.time() + 20
        while dataprovider._running and time.time() < deadline:
            qgis_app.processEvents()
            time.sleep(0.005)
        assert not dataprovider._running, "sync did not finish"
        for _ in range(3):  # deferred reloads (QTimer 0)
            qgis_app.processEvents()

    def seed():
        """Fill the cache like a previous session did."""
        dataprovider.sync_now(VID)
        server.calls.clear()

    yield types.SimpleNamespace(
        server=server,
        cache=cache,
        dp=dataprovider,
        events=events,
        open_layer=open_layer,
        wait=wait,
        seed=seed,
        root=root,
    )
    server.error = server.diff_error = None
    wait()
    events.clear()
    for layer in layers:
        if layer.isValid() and layer.id() in QgsProject.instance().mapLayers():
            if layer.isEditable():
                layer.rollBack()
            QgsProject.instance().removeMapLayer(layer.id())
    for signal, handler in handlers:
        signal.disconnect(handler)
    dataprovider._rerun.clear()


def _names(layer):
    return {f.id(): f["name"] for f in layer.getFeatures()}


class TestOpen:
    def test_with_cache_opens_without_network(self, env):
        env.server.add_row(1, name="a")
        env.seed()

        layer = env.open_layer()

        assert layer.isValid()
        assert "get_vector" not in env.server.names()
        assert _names(layer) == {1: "a"}
        assert layer.fields().names() == ["kumoy_id", "name"]
        assert ("started", VID) in env.events  # background sync follows
        env.wait()

    def test_first_open_downloads_in_background(self, env):
        env.server.add_row(1, name="a")

        layer = env.open_layer()

        assert layer.isValid()
        assert env.server.names()[0] == "get_vector"  # the one blocking call
        assert layer.featureCount() == 0
        assert not layer.dataProvider().capabilities() & ADD
        changed = []
        layer.dataChanged.connect(lambda: changed.append(1))

        env.wait()

        assert changed
        assert _names(layer) == {1: "a"}
        assert layer.featureCount() == 1
        assert layer.dataProvider().capabilities() & ADD

    def test_primed_metadata_avoids_the_request(self, env):
        env.dp.prime_vector(env.server.detail())
        layer = env.open_layer()
        assert layer.isValid()
        assert "get_vector" not in env.server.names()

    def test_first_open_offline_is_invalid_and_reported(self, env):
        from plugin_dir.kumoy.api.error import NetworkError

        env.server.error = NetworkError("offline")
        layer = env.open_layer()
        assert not layer.isValid()
        assert "offline" in layer.dataProvider().error().message()
        assert env.events[-1][0] == "failed"

    def test_create_vector_layer_raises_translated_error(self, env, monkeypatch):
        from plugin_dir.kumoy import constants, vector_layer
        from plugin_dir.kumoy.api.error import NotFoundError

        monkeypatch.setattr(constants, "DATA_PROVIDER_KEY", TEST_KEY)
        env.server.error = NotFoundError("Vector not found")
        vector = types.SimpleNamespace(id=VID, name="vec", type="POINT", projectId="p1")
        with pytest.raises(RuntimeError, match="Vector not found"):
            vector_layer.create_vector_layer(vector)

    def test_offline_with_cache_keeps_data_and_reports(self, env):
        from plugin_dir.kumoy.api.error import NetworkError

        env.server.add_row(1, name="a")
        env.seed()
        env.server.error = NetworkError("offline")

        layer = env.open_layer()
        env.wait()

        assert layer.isValid()
        assert _names(layer) == {1: "a"}
        failed = [e for e in env.events if e[0] == "failed"]
        assert failed and failed[0][1] == VID and "offline" in failed[0][2]
        assert isinstance(failed[0][3], NetworkError)

    def test_layers_of_one_vector_share_one_sync(self, env):
        env.seed()
        env.open_layer()
        env.open_layer()
        env.wait()
        assert env.server.names().count("get_vector_and_server_time") == 1

    def test_viewer_is_read_only(self, env):
        env.server.role = "MEMBER"
        env.seed()
        layer = env.open_layer()
        caps = layer.dataProvider().capabilities()
        assert not caps & ADD
        assert not layer.startEditing()

    def test_subset_from_uri(self, env):
        env.server.add_row(1, name="a")
        env.server.add_row(2, name="b")
        env.seed()
        layer = env.open_layer(subset="\"name\" = 'b'")
        assert _names(layer) == {2: "b"}
        assert layer.featureCount() == 1
        layer.setSubsetString("")
        assert "subset" not in layer.dataProvider().dataSourceUri()
        assert layer.featureCount() == 2

    def test_opened_in_worker_thread_downloads_synchronously(self, env):
        env.server.add_row(1, name="a")
        result = {}

        def work():
            layer = QgsVectorLayer(
                f"project_id=p1;vector_id={VID};vector_name=vec;vector_type=POINT",
                "vec",
                TEST_KEY,
            )
            result["features"] = [f["name"] for f in layer.getFeatures()]

        t = threading.Thread(target=work)
        t.start()
        t.join(20)
        assert result["features"] == ["a"]


class TestSync:
    def test_diff_uses_server_clock_with_margin(self, env):
        env.server.add_row(1, name="a")
        env.server.add_row(2, name="b")
        env.seed()  # last_updated = server date - margin
        layer = env.open_layer()
        env.wait()
        diff_calls = [c for c in env.server.calls if c[0] == "get_diff"]
        assert diff_calls == [("get_diff", ("2026-11-17T11:59:00Z",))]

        env.server.rows[1]["properties"]["name"] = "A"
        env.server.rows.pop(2)
        env.server.add_row(3, name="c")
        env.server.pending_diff = ([1, 3], [2])
        layer.dataProvider().sync()
        env.wait()

        assert _names(layer) == {1: "A", 3: "c"}
        assert layer.featureCount() == 2

    def test_max_diff_count_rebuilds_into_new_file(self, env):
        from plugin_dir.kumoy.api.error import AppError

        env.server.add_row(1, name="a")
        env.seed()
        layer = env.open_layer()
        env.wait()
        old_path = env.cache.open_cache(VID).path

        env.server.add_row(2, name="b")
        env.server.diff_error = AppError("Application Error", "MAX_DIFF_COUNT_EXCEEDED")
        layer.dataProvider().sync()
        env.wait()

        assert env.cache.open_cache(VID).path != old_path
        assert _names(layer) == {1: "a", 2: "b"}

    def test_failed_rebuild_keeps_current_cache(self, env, monkeypatch):
        monkeypatch.setattr(env.dp, "FEATURES_PAGE_SIZE", 1)
        env.server.add_row(1, name="a")
        env.server.add_row(2, name="b")
        env.seed()
        before = env.cache.open_cache(VID)
        env.server.columns = env.server.columns[:0]  # schema change -> rebuild
        env.server.features_error_after = 1

        with pytest.raises(RuntimeError):
            env.dp.sync_now(VID)

        after = env.cache.open_cache(VID)
        assert after.path == before.path
        assert (
            len(list(env.root.joinpath(VID).glob("*.gpkg"))) == 1
        )  # unfinished removed

    def test_paged_download(self, env, monkeypatch):
        monkeypatch.setattr(env.dp, "FEATURES_PAGE_SIZE", 2)
        for i in range(5):
            env.server.add_row(i, name=str(i))
        layer = env.open_layer()
        env.wait()
        assert layer.featureCount() == 5
        afters = [c[1][0] for c in env.server.calls if c[0] == "get_features"]
        assert afters == [None, 2, 4]

    def test_new_and_removed_columns_reach_layer_and_attribute_table(self, env):
        from plugin_dir.kumoy.api.models import Column
        from qgis.gui import QgsAttributeTableModel

        env.server.add_row(1, name="a", n=5)
        env.seed()
        layer = env.open_layer()
        env.wait()
        layer_cache = QgsVectorLayerCache(layer, 100)  # the model does not own it
        model = QgsAttributeTableModel(layer_cache)
        model.loadLayer()
        assert model.columnCount() == 2

        env.server.columns = [Column("n", "integer")]
        env.server.add_row(2, n=6)
        layer.dataProvider().sync()
        env.wait()

        assert layer.fields().names() == ["kumoy_id", "n"]
        assert {f.id(): f["n"] for f in layer.getFeatures()} == {1: 5, 2: 6}
        assert model.columnCount() == 2
        assert model.rowCount() == 2
        assert (
            model.headerData(1, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
            == "n"
        )

    def test_cancel_is_reported_as_canceled(self, env):
        from plugin_dir.kumoy.tasks import Canceled

        env.seed()
        env.server.gate = threading.Event()
        env.dp.sync_vector(VID)
        env.dp._running[VID].cancel()
        env.server.gate.set()
        env.wait()
        failed = [e for e in env.events if e[0] == "failed"]
        assert len(failed) == 1 and isinstance(failed[0][3], Canceled)

    def test_source_snapshot_survives_cache_swap(self, env):
        from plugin_dir.kumoy.api.error import AppError

        env.server.add_row(1, name="a")
        env.seed()
        layer = env.open_layer()
        env.wait()
        source = layer.dataProvider().featureSource()

        env.server.add_row(2, name="b")
        env.server.diff_error = AppError("x", "MAX_DIFF_COUNT_EXCEEDED")
        layer.dataProvider().sync()
        env.wait()

        assert [f["name"] for f in source.getFeatures(QgsFeatureRequest())] == ["a"]
        assert _names(layer) == {1: "a", 2: "b"}


class TestRead:
    def test_destination_crs_transforms_once(self, env):
        env.server.add_row(1, name="a")
        env.seed()
        layer = env.open_layer()
        request = QgsFeatureRequest().setDestinationCrs(
            QgsCoordinateReferenceSystem("EPSG:3857"),
            QgsProject.instance().transformContext(),
        )
        point = next(layer.getFeatures(request)).geometry().asPoint()
        assert point.x() == pytest.approx(111319.49, abs=0.1)
        point = next(layer.dataProvider().getFeatures(request)).geometry().asPoint()
        assert point.x() == pytest.approx(111319.49, abs=0.1)

    def test_attributes_are_matched_by_name_until_rebuilt(self, env):
        env.server.add_row(1, name="a")
        env.seed()
        layer = env.open_layer()
        env.wait()
        provider = layer.dataProvider()
        # As after addAttributes: the cache file has no such column yet
        provider._added_fields.clear()
        from plugin_dir.kumoy.api.models import Column

        provider._set_columns([Column("extra", "integer"), Column("name", "string")])

        f = next(provider.getFeatures())
        assert f.fields().names() == ["kumoy_id", "extra", "name"]
        assert f.attributes()[0] == 1 and f["name"] == "a" and f["extra"] == NULL
        request = QgsFeatureRequest().setSubsetOfAttributes([2])
        assert next(provider.getFeatures(request))["name"] == "a"


def _point(x, y=0.0):
    return QgsGeometry.fromPointXY(QgsPointXY(x, y))


class TestEdit:
    @pytest.fixture
    def layer(self, env):
        env.server.add_row(1, name="a")
        env.seed()
        layer = env.open_layer()
        env.wait()
        env.server.calls.clear()
        return layer

    def _new(self, layer, geometry, name="n"):
        f = QgsFeature(layer.fields())
        f.setGeometry(geometry)
        f["name"] = name
        return f

    def test_add_assigns_server_ids_and_converts_multi(self, env, layer):
        assert layer.startEditing()
        f1 = self._new(layer, QgsGeometry.fromWkt("MultiPoint ((3 4))"), "m")
        f2 = self._new(layer, QgsGeometry.fromWkt("Point Z (5 6 7)"), "z")
        assert layer.addFeatures([f1, f2])
        assert layer.commitChanges(), layer.commitErrors()

        sent = [c for c in env.server.calls if c[0] == "add_features"][0][1][0]
        assert [s["properties"] for s in sent] == [{"name": "m"}, {"name": "z"}]
        assert env.server.rows[2]["kumoy_wkb"] == bytes(_point(3, 4).asWkb())
        assert env.server.rows[3]["kumoy_wkb"] == bytes(_point(5, 6).asWkb())
        # Visible at once with the server ids, before any sync
        assert _names(layer) == {1: "a", 2: "m", 3: "z"}
        assert layer.getFeature(2)["kumoy_id"] == 2
        env.wait()
        assert _names(layer) == {1: "a", 2: "m", 3: "z"}

    def test_incompatible_geometry_fails_clearly(self, env, layer):
        assert layer.startEditing()
        layer.addFeature(
            self._new(layer, QgsGeometry.fromWkt("MultiPoint ((1 1),(2 2))"))
        )
        assert not layer.commitChanges()
        assert "2 parts" in " ".join(layer.commitErrors())
        assert "add_features" not in env.server.names()

        layer.rollBack()
        assert layer.startEditing()
        layer.addFeature(self._new(layer, QgsGeometry.fromWkt("LineString (0 0, 1 1)")))
        assert not layer.commitChanges()
        assert "add_features" not in env.server.names()

    def test_add_in_chunks(self, env, layer):
        features = [self._new(layer, _point(i)) for i in range(2500)]
        ok, out = layer.dataProvider().addFeatures(features)
        assert ok
        sizes = [len(c[1][0]) for c in env.server.calls if c[0] == "add_features"]
        assert sizes == [1000, 1000, 500]
        assert sorted(f.id() for f in out) == list(range(2, 2502))

    def test_api_error_is_pushed(self, env, layer):
        from plugin_dir.kumoy.api.error import ForbiddenError

        env.server.error = ForbiddenError("Forbidden", "no role")
        ok, _ = layer.dataProvider().addFeatures([self._new(layer, _point(1))])
        assert not ok
        errors = " ".join(layer.dataProvider().errors())
        assert "permission" in errors and "no role" in errors
        assert not layer.dataProvider().deleteFeatures([1])

    def test_change_attributes_geometry_and_delete(self, env, layer):
        assert layer.startEditing()
        layer.changeAttributeValue(1, 1, "renamed")
        layer.changeGeometry(1, QgsGeometry.fromWkt("MultiPoint ((8 9))"))
        assert layer.commitChanges(), layer.commitErrors()

        items = [c for c in env.server.calls if c[0] == "change_geometry_values"][0][1][
            0
        ]
        assert base64.b64decode(items[0]["kumoy_wkb"]) == bytes(_point(8, 9).asWkb())
        f = layer.getFeature(1)
        assert f["name"] == "renamed"
        assert f.geometry().asWkt() == "Point (8 9)"

        assert layer.startEditing()
        assert layer.deleteFeature(1)
        assert layer.commitChanges(), layer.commitErrors()
        assert _names(layer) == {}
        env.wait()  # the count is refreshed once control returns to the event loop
        assert layer.featureCount() == 0

    def test_add_attribute_then_values_after_rebuild(self, env, layer, qgis_app):
        env.server.gate = threading.Event()
        assert layer.startEditing()
        assert layer.addAttribute(QgsField("score", QMetaType.Type.LongLong))
        # No length: differs from the 255 the provider reports for strings,
        # which must not make the commit fail
        assert layer.addAttribute(QgsField("memo", QMetaType.Type.QString))
        layer.changeAttributeValue(1, layer.fields().indexOf("score"), 42)
        layer.changeAttributeValue(1, layer.fields().indexOf("memo"), "hi")
        assert layer.commitChanges(), layer.commitErrors()

        assert [(c.name, c.type) for c in env.server.columns[-2:]] == [
            ("score", "integer"),
            ("memo", "string"),
        ]
        for _ in range(5):  # deferred reload while the sync still runs
            qgis_app.processEvents()
        assert layer.fields().names() == ["kumoy_id", "name", "score", "memo"]
        assert layer.getFeature(1)["name"] == "a"
        env.server.gate.set()
        env.wait()  # schema changed -> rebuild
        assert layer.fields().names() == ["kumoy_id", "name", "score", "memo"]
        assert layer.getFeature(1)["score"] == 42
        assert layer.getFeature(1)["memo"] == "hi"

    def test_delete_attribute(self, env, layer):
        assert layer.startEditing()
        assert layer.deleteAttribute(1)
        assert layer.commitChanges(), layer.commitErrors()
        assert layer.fields().names() == ["kumoy_id"]
        env.wait()
        assert layer.fields().names() == ["kumoy_id"]
        assert layer.featureCount() == 1

    def test_kumoy_id_cannot_be_deleted(self, env, layer):
        assert not layer.dataProvider().deleteAttributes([0])
        assert "delete_attributes" not in env.server.names()


class TestUri:
    def test_round_trip_keeps_semicolons_in_subset(self, qgis_plugin_path):
        from plugin_dir.kumoy.provider.dataprovider import decode_uri, encode_uri

        uri = (
            "project_id=p;vector_id=v;vector_name=a b;vector_type=POINT;"
            "subset=\"x\" = 'a;b'"
        )
        parts = decode_uri(uri)
        assert parts == {
            "project_id": "p",
            "vector_id": "v",
            "vector_name": "a b",
            "vector_type": "POINT",
            "subset": "\"x\" = 'a;b'",
        }
        assert encode_uri(parts) == uri

    def test_vector_uri_format_is_unchanged(self, qgis_plugin_path):
        from plugin_dir.kumoy.vector_layer import vector_uri

        vector = types.SimpleNamespace(id="v", name="n", type="POINT", projectId="p")
        assert vector_uri(vector) == (
            "project_id=p;vector_id=v;vector_name=n;vector_type=POINT;"
        )
