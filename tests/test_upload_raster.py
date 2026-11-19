"""ui/layers/_upload_raster.upload: runs the upload algorithm in the background.

A stub algorithm stands in for kumoy:uploadraster (area E) and plays the
success, failure and cancel outcomes.
"""

import time

import pytest

_behaviour = {"mode": "ok", "params": None}


def _wait(condition, timeout=10.0):
    from qgis.PyQt.QtCore import QCoreApplication

    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        QCoreApplication.processEvents()
        time.sleep(0.01)


@pytest.fixture(scope="module")
def stub_algorithm(qgis_app):
    from osgeo import gdal, osr
    from qgis.core import (
        QgsApplication,
        QgsProcessingAlgorithm,
        QgsProcessingException,
        QgsProcessingParameterRasterLayer,
        QgsProcessingParameterString,
        QgsProcessingProvider,
        QgsProviderRegistry,
    )

    from plugin_dir.kumoy.local_cache import raster as raster_cache
    from plugin_dir.kumoy.provider.raster_dataprovider_metadata import (
        KumoyRasterProviderMetadata,
    )

    QgsProviderRegistry.instance().registerProvider(KumoyRasterProviderMetadata())

    class Upload(QgsProcessingAlgorithm):
        def name(self):
            return "uploadraster"

        def displayName(self):
            return "stub upload"

        def createInstance(self):
            return Upload()

        def initAlgorithm(self, config=None):
            self.addParameter(QgsProcessingParameterRasterLayer("INPUT", "in"))
            self.addParameter(QgsProcessingParameterString("PROJECT_ID", "p"))
            self.addParameter(QgsProcessingParameterString("RASTER_NAME", "n"))

        def processAlgorithm(self, parameters, context, feedback):
            _behaviour["params"] = dict(parameters)
            feedback.setProgress(50)
            if _behaviour["mode"] == "fail":
                feedback.reportError("Raster limit reached")
                raise QgsProcessingException("Raster limit reached")
            if _behaviour["mode"] == "cancel":
                while not feedback.isCanceled():
                    time.sleep(0.01)
                return {}
            # Like the real algorithm: the uploaded COG goes into the cache
            path = raster_cache.get_cache_path("r-new") + ".src"
            ds = gdal.GetDriverByName("GTiff").Create(path, 4, 4, 1, gdal.GDT_Byte)
            ds.SetGeoTransform([0, 1, 0, 4, 0, -1])
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(4326)
            ds.SetProjection(srs.ExportToWkt())
            ds = None
            raster_cache.store("r-new", path)
            return {"RASTER_ID": "r-new"}

    class Provider(QgsProcessingProvider):
        def id(self):
            return "kumoyuploadtest"

        def name(self):
            return "stub"

        def loadAlgorithms(self):
            self.addAlgorithm(Upload())

    provider = Provider()
    QgsApplication.processingRegistry().addProvider(provider)
    yield "kumoyuploadtest:uploadraster"
    QgsApplication.processingRegistry().removeProvider(provider)


@pytest.fixture
def upload(stub_algorithm, tmp_path, monkeypatch):
    from qgis.core import QgsRasterLayer

    from plugin_dir.kumoy.local_cache import raster as raster_cache
    from plugin_dir.ui.layers import _upload_raster

    monkeypatch.setattr(raster_cache, "_get_cache_dir", lambda: str(tmp_path))
    monkeypatch.setattr(_upload_raster, "_ALGORITHM_ID", stub_algorithm)
    source = QgsRasterLayer(str(tmp_path / "none.tif"), "local dem", "gdal")
    events = []

    def start(mode):
        _behaviour["mode"] = mode
        _behaviour["params"] = None
        return _upload_raster.upload(
            source,
            "p-1",
            "dem",
            on_progress=lambda p: events.append(("progress", p)),
            on_done=lambda layer: events.append(("done", layer)),
            on_error=lambda e: events.append(("error", str(e))),
        )

    start.events = events
    return start


def test_success_returns_cached_kumoy_layer(upload):
    upload("ok")
    _wait(lambda: any(e[0] in ("done", "error") for e in upload.events))

    assert _behaviour["params"]["PROJECT_ID"] == "p-1"
    assert _behaviour["params"]["RASTER_NAME"] == "dem"
    [(kind, layer)] = [e for e in upload.events if e[0] != "progress"]
    assert kind == "done"
    assert layer.isValid() and layer.width() == 4  # read from the cache
    assert layer.name() == "dem"
    assert "raster_id=r-new" in layer.source()
    assert ("progress", 50.0) in upload.events


def test_failure_reports_algorithm_message(upload):
    upload("fail")
    _wait(lambda: any(e[0] in ("done", "error") for e in upload.events))

    assert [e for e in upload.events if e[0] != "progress"] == [
        ("error", "Raster limit reached")
    ]


def test_cancel_is_silent(upload):
    task = upload("cancel")
    _wait(lambda: _behaviour["params"] is not None)
    task.cancel()
    _wait(lambda: any(e[0] in ("done", "error") for e in upload.events))

    assert [e for e in upload.events if e[0] != "progress"] == [("done", None)]
