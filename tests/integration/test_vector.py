"""Vector round trip: upload tool, provider, edits, background sync."""

import pytest

from .conftest import pump, wait_for_tasks, wait_until


class SyncCounter:
    """Counts sync_finished / sync_failed of one vector."""

    def __init__(self, vector_id: str):
        from plugin_dir.kumoy.provider.dataprovider import sync_events

        self.vector_id = vector_id
        self.finished = 0
        self.failures = []
        sync_events.sync_finished.connect(self._finished)
        sync_events.sync_failed.connect(self._failed)

    def _finished(self, vector_id):
        if vector_id == self.vector_id:
            self.finished += 1

    def _failed(self, vector_id, message, _e):
        if vector_id == self.vector_id:
            self.failures.append(message)

    def wait(self, after: int) -> None:
        """Wait for a sync finishing after `after` had, then for the reload."""
        wait_until(lambda: self.finished > after or self.failures, 60, "vector sync")
        assert not self.failures
        wait_for_tasks()  # edits queue a re-run
        pump(0.2)  # provider reload is deferred to the event loop


def _memory_layer():
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer

    layer = QgsVectorLayer(
        "Point?crs=EPSG:3857&field=name:string&field=n:integer&field=f:double",
        "e2e-points",
        "memory",
    )
    features = []
    for i in range(3):
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(100000 * (i + 1), 0)))
        f.setAttributes([f"p{i}", i, i + 0.5])
        features.append(f)
    layer.dataProvider().addFeatures(features)
    return layer


def _attrs(layer, *names):
    return sorted(tuple(f[n] for n in names) for f in layer.getFeatures())


@pytest.fixture(scope="module")
def uploaded(project):
    """A vector uploaded with the Processing tool."""
    import processing
    from qgis.core import QgsProject

    from plugin_dir.kumoy import api

    source = _memory_layer()
    QgsProject.instance().addMapLayer(source)
    result = processing.run(
        "kumoy:uploadvector",
        {"INPUT": source, "PROJECT_ID": project.id, "VECTOR_NAME": "e2e-upload"},
    )
    QgsProject.instance().removeMapLayer(source.id())
    vector_id = result["VECTOR_ID"]
    yield api.vector.get_vector(vector_id)
    api.vector.delete_vector(vector_id)


def test_upload_tool(uploaded):
    assert uploaded.name == "e2e-upload"
    assert uploaded.type == "POINT"
    assert uploaded.count == 3
    assert [(c.name, c.type) for c in uploaded.columns] == [
        ("name", "string"),
        ("n", "integer"),
        ("f", "float"),
    ]


def test_provider_read_edit_and_sync(uploaded):
    from qgis.core import QgsFeature, QgsField, QgsGeometry, QgsPointXY, QgsProject
    from qgis.PyQt.QtCore import QMetaType

    from plugin_dir.kumoy import api, local_cache
    from plugin_dir.kumoy.vector_layer import create_vector_layer

    local_cache.vector.clear(uploaded.id)
    syncs = SyncCounter(uploaded.id)
    layer = create_vector_layer(uploaded)
    QgsProject.instance().addMapLayer(layer)
    try:
        # No cache: valid at once with the server's fields, filled by the sync
        assert layer.fields().names() == ["kumoy_id", "name", "n", "f"]
        syncs.wait(0)
        assert layer.featureCount() == 3
        assert _attrs(layer, "name", "n", "f") == [
            ("p0", 0, 0.5),
            ("p1", 1, 1.5),
            ("p2", 2, 2.5),
        ]
        first = next(layer.getFeatures())
        point = first.geometry().asPoint()
        assert point.y() == pytest.approx(0, abs=1e-9)
        assert 0.8 < point.x() < 1.0  # 100 km east of 0,0 in degrees
        assert first.id() == first["kumoy_id"]

        # Edit through the layer: everything is sent on commit
        by_name = {f["name"]: f for f in layer.getFeatures()}
        assert layer.startEditing()
        new = QgsFeature(layer.fields())
        new.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(10, 20)))
        new.setAttribute("name", "new")
        new.setAttribute("n", 42)
        assert layer.addFeature(new)
        name_idx = layer.fields().indexOf("name")
        assert layer.changeAttributeValue(by_name["p0"].id(), name_idx, "renamed")
        assert layer.changeGeometry(
            by_name["p1"].id(), QgsGeometry.fromPointXY(QgsPointXY(5, 6))
        )
        assert layer.deleteFeature(by_name["p2"].id())
        before = syncs.finished
        assert layer.commitChanges(), layer.commitErrors()
        syncs.wait(before)

        rows = {
            r["properties"]["name"]: r
            for r in api.qgis_vector.get_features(uploaded.id)
        }
        assert set(rows) == {"renamed", "p1", "new"}
        assert rows["new"]["properties"]["n"] == 42
        moved = QgsGeometry()
        moved.fromWkb(rows["p1"]["kumoy_wkb"])
        assert moved.asPoint() == QgsPointXY(5, 6)
        assert _attrs(layer, "name") == [("new",), ("p1",), ("renamed",)]
        # The layer's new feature has the server's id
        new_id = rows["new"]["kumoy_id"]
        assert layer.getFeature(new_id)["name"] == "new"

        # Someone else edits: the diff sync brings it into the cache and layer
        api.qgis_vector.change_attribute_values(
            uploaded.id, [{"kumoy_id": new_id, "properties": {"name": "remote"}}]
        )
        api.qgis_vector.delete_features(uploaded.id, [rows["p1"]["kumoy_id"]])
        before = syncs.finished
        layer.dataProvider().sync()
        syncs.wait(before)
        assert _attrs(layer, "name") == [("remote",), ("renamed",)]

        # A column added elsewhere changes the schema: the cache is rebuilt
        api.qgis_vector.add_attributes(
            uploaded.id, [{"name": "remote_col", "type": "boolean"}]
        )
        old_path = layer.dataProvider()._cache_path
        before = syncs.finished
        layer.dataProvider().sync()
        syncs.wait(before)
        assert layer.fields().names()[-1] == "remote_col"
        assert layer.featureCount() == 2
        # A new file, not the old one altered (readers may hold it open)
        assert layer.dataProvider()._cache_path != old_path

        # A column added in QGIS, then filled
        assert layer.startEditing()
        assert layer.addAttribute(QgsField("score", QMetaType.Type.LongLong))
        before = syncs.finished
        assert layer.commitChanges(), layer.commitErrors()
        syncs.wait(before)
        assert "score" in layer.fields().names()
        assert layer.startEditing()
        score_idx = layer.fields().indexOf("score")
        assert layer.changeAttributeValue(new_id, score_idx, 7)
        assert layer.commitChanges(), layer.commitErrors()
        wait_for_tasks()
        pump(0.2)
        assert layer.getFeature(new_id)["score"] == 7
        columns = [c.name for c in api.vector.get_vector(uploaded.id).columns]
        assert columns[-2:] == ["remote_col", "score"]

        # Delete a column in QGIS
        assert layer.startEditing()
        assert layer.deleteAttribute(layer.fields().indexOf("remote_col"))
        assert layer.commitChanges(), layer.commitErrors()
        wait_for_tasks()
        pump(0.2)
        assert "remote_col" not in [
            c.name for c in api.vector.get_vector(uploaded.id).columns
        ]
        assert "remote_col" not in layer.fields().names()
    finally:
        QgsProject.instance().removeMapLayer(layer.id())
        wait_for_tasks()


def test_open_from_cache_without_request(uploaded):
    """A cached vector opens offline (no request) and syncs in the background."""
    from qgis.core import QgsProject

    from plugin_dir.kumoy import session
    from plugin_dir.kumoy.api.models import Vector
    from plugin_dir.kumoy.vector_layer import create_vector_layer

    wait_for_tasks()
    plain = Vector(uploaded.id, uploaded.name, uploaded.type, uploaded.projectId)
    saved = session._token
    session._token = None  # any request would fail
    try:
        layer = create_vector_layer(plain)
        assert layer.isValid()
        assert layer.featureCount() > 0
        QgsProject.instance().addMapLayer(layer)
        QgsProject.instance().removeMapLayer(layer.id())
    finally:
        session._token = saved
    wait_for_tasks()


def test_open_in_worker_thread(uploaded):
    """Off the main thread (Processing in the toolbox) the provider downloads
    the features before returning instead of syncing in the background."""
    from qgis.core import QgsVectorLayer

    from plugin_dir.kumoy import constants, local_cache
    from plugin_dir.kumoy.tasks import run_task
    from plugin_dir.kumoy.vector_layer import vector_uri

    wait_for_tasks()
    local_cache.vector.clear(uploaded.id)
    results = []

    def open_layer(_task):
        layer = QgsVectorLayer(vector_uri(uploaded), "w", constants.DATA_PROVIDER_KEY)
        return layer.isValid(), layer.featureCount()

    run_task("open", open_layer, results.append, results.append)
    wait_until(lambda: results, 60, "worker task")
    assert results[0][0] is True and results[0][1] > 0


def test_upload_lines_with_all_field_types(project):
    """Multi-part lines (split), dates, booleans, NULLs and non-ASCII text."""
    import processing
    from qgis.core import QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer
    from qgis.PyQt.QtCore import QDate, QDateTime, QTime

    from plugin_dir.kumoy import api

    source = QgsVectorLayer(
        "MultiLineString?crs=EPSG:4326&field=jp:string&field=flag:boolean"
        "&field=d:date&field=dt:datetime&field=big:long&field=kumoy_x:integer",
        "lines",
        "memory",
    )
    f = QgsFeature(source.fields())
    f.setGeometry(QgsGeometry.fromWkt("MultiLineString((0 0, 1 1), (2 2, 3 3))"))
    f.setAttributes(
        [
            "日本語",
            True,
            QDate(2026, 11, 17),
            QDateTime(QDate(2026, 11, 17), QTime(12, 34, 56)),
            2**40,
            1,
        ]
    )
    empty = QgsFeature(source.fields())
    empty.setGeometry(QgsGeometry.fromWkt("MultiLineString((5 5, 6 6))"))
    source.dataProvider().addFeatures([f, empty])
    QgsProject.instance().addMapLayer(source)
    try:
        vector_id = processing.run(
            "kumoy:uploadvector", {"INPUT": source, "PROJECT_ID": project.id}
        )["VECTOR_ID"]
    finally:
        QgsProject.instance().removeMapLayer(source.id())
    try:
        detail = api.vector.get_vector(vector_id)
        assert detail.type == "LINESTRING"
        # kumoy_ is reserved: skipped
        assert [(c.name, c.type) for c in detail.columns] == [
            ("jp", "string"),
            ("flag", "boolean"),
            ("d", "string"),
            ("dt", "string"),
            ("big", "integer"),
        ]
        rows = api.qgis_vector.get_features(vector_id)
        assert len(rows) == 3  # the multi-part line became two features
        props = [r["properties"] for r in rows]
        assert props[0] == props[1]
        assert props[0]["jp"] == "日本語" and props[0]["flag"] is True
        assert props[0]["d"] == "2026-11-17"
        assert props[0]["dt"].startswith("2026-11-17T12:34:56")
        assert props[0]["big"] == 2**40
        assert all(v is None for v in props[2].values())
    finally:
        api.vector.delete_vector(vector_id)


def test_large_diff_reloads_everything(uploaded):
    """Over 1000 changed rows the server refuses the diff: full download."""
    from qgis.core import QgsGeometry, QgsPointXY, QgsProject

    from plugin_dir.kumoy import api
    from plugin_dir.kumoy.vector_layer import create_vector_layer

    wait_for_tasks()
    qv = api.qgis_vector
    layer = create_vector_layer(api.vector.get_vector(uploaded.id))
    QgsProject.instance().addMapLayer(layer)
    try:
        wait_for_tasks()
        pump(0.2)
        before = layer.featureCount()
        wkb = qv.encode_wkb(bytes(QgsGeometry.fromPointXY(QgsPointXY(1, 1)).asWkb()))
        for _ in range(2):  # at most 1000 per request
            qv.add_features(uploaded.id, [{"kumoy_wkb": wkb, "properties": {}}] * 600)
        syncs = SyncCounter(uploaded.id)
        layer.dataProvider().sync()
        syncs.wait(0)
        assert layer.featureCount() == before + 1200
    finally:
        QgsProject.instance().removeMapLayer(layer.id())
        wait_for_tasks()
