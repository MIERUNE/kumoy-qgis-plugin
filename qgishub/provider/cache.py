import itertools
import os
from dataclasses import dataclass
from functools import lru_cache

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsRectangle,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant

from .. import api


def get_cache_dir() -> str:
    """Return the directory where cache files are stored."""
    cache_dir = QgsApplication.qgisSettingsDirPath()
    if not cache_dir.endswith("/"):
        cache_dir += "/"
    return cache_dir + "cache/"


def sync_local_cache(
    vector_id: str, fields: QgsFields, geometry_type: QgsWkbTypes.GeometryType
):
    # create empty GeoPackage cache for the vector
    """Initialize a local cache for the vector with the given ID."""

    cache_dir = get_cache_dir()
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

    cache_file = os.path.join(cache_dir, f"{vector_id}.gpkg")
    if os.path.exists(cache_file):
        print(f"Cache file {cache_file} already exists. Skipping creation.")
        return cache_file

    writer = QgsVectorFileWriter(
        cache_file,
        "UTF-8",
        fields,
        geometry_type,
        QgsCoordinateReferenceSystem("EPSG:4326"),
        "GPKG",
    )

    if writer.hasError() != QgsVectorFileWriter.NoError:
        QgsApplication.messageLog().logMessage(
            f"Error creating cache file {cache_file}: {writer.errorMessage()}",
            Qgis.Critical,
        )
        return None

    # memo: 一旦差分のことは考えないで毎回全件取得する
    BATCH_SIZE = 5000  # Number of features to fetch in each batch
    count = 0
    while True:
        # Fetch features in batches
        features = api.qgis_vector.get_features(
            vector_id=vector_id,
            limit=BATCH_SIZE,
            offset=count * BATCH_SIZE,
        )
        print(f"Fetched {len(features)} features for {vector_id} (batch {count})")

        for feature in features:
            qgsfeature = QgsFeature()
            wkb = feature["qgishub_wkb"]
            fid = feature["qgishub_id"]

            # Set geometry
            g = QgsGeometry()
            g.fromWkb(wkb)
            qgsfeature.setGeometry(g)

            # Set attributes
            # feature["properties"] = { field_name: value, ... }
            qgsfeature.setFields(fields)
            for i in range(qgsfeature.fields().count()):
                qgsfeature.setAttribute(
                    i, feature["properties"][qgsfeature.fields().field(i).name()]
                )

            # Set feature ID and validity
            qgsfeature.setId(fid)
            qgsfeature.setValid(True)
            # 地物を書き込み
            writer.addFeature(qgsfeature)

        if len(features) < BATCH_SIZE:
            break
        count += 1

    del writer


LAYER_CACHE = {}


@lru_cache(maxsize=128)
def get_cached_layer(vector_id: str) -> QgsVectorLayer:
    """Retrieve a cached QgsVectorLayer by vector ID."""
    cache_dir = get_cache_dir()
    cache_file = os.path.join(cache_dir, f"{vector_id}.gpkg")
    layer = QgsVectorLayer(cache_file, "cache", "ogr")
    if layer.isValid():
        return layer
    else:
        QgsApplication.messageLog().logMessage(
            f"Cache layer {vector_id} is not valid.", Qgis.Critical
        )
        return None


def get_features(
    vector_id: str, limit: int, offset: int, bbox: QgsRectangle = None, ids: list = None
):
    """Fetch features from the local cache."""

    if vector_id not in LAYER_CACHE:
        cache_dir = get_cache_dir()
        cache_file = os.path.join(cache_dir, f"{vector_id}.gpkg")
        layer = QgsVectorLayer(cache_file, "cache", "ogr")
        LAYER_CACHE[vector_id] = layer

    layer = LAYER_CACHE[vector_id]
    if not layer.isValid():
        return []

    request = QgsFeatureRequest()
    if ids:
        request.setFilterFids(ids)  # IDフィルタ
    if bbox:
        request.setFilterRect(bbox)  # 空間フィルタ

    features = [
        feature
        for feature in itertools.islice(
            layer.getFeatures(request), offset, offset + limit
        )
    ]

    return features
