import itertools
import os
from dataclasses import dataclass
from functools import lru_cache

from qgis.core import (
    Qgis,
    QgsApplication,
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

from .. import api


def get_cache_dir() -> str:
    """Return the directory where cache files are stored."""
    cache_dir = QgsApplication.qgisSettingsDirPath()
    if not cache_dir.endswith("/"):
        cache_dir += "/"
    cache_dir = cache_dir + "cache/"

    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

    return cache_dir


# TODO: 差分更新
def sync_local_cache(
    vector_id: str, fields: QgsFields, geometry_type: QgsWkbTypes.GeometryType
):
    """
    サーバー上のデータとローカルのキャッシュを同期する
    - キャッシュはGPKGを用いる
    - ローカルにGPKGが存在しなければ新規で作成する
    - この関数の実行時、サーバー上のデータとの差分を取得してローカルのキャッシュを更新する
    """

    cache_dir = get_cache_dir()
    cache_file = os.path.join(cache_dir, f"{vector_id}.gpkg")

    if os.path.exists(cache_file):
        return

    new_fields = QgsFields(fields)
    new_fields.append(QgsField("qgishub_id", QVariant.Int))

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.layerOptions = ["FID=qgishub_id"]
    options.driverName = "GPKG"
    options.fileEncoding = "UTF-8"

    writer = QgsVectorFileWriter.create(
        cache_file,
        new_fields,
        geometry_type,
        QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsProject.instance().transformContext(),
        options,
    )

    if writer.hasError() != QgsVectorFileWriter.NoError:
        QgsApplication.messageLog().logMessage(
            f"Error creating cache file {cache_file}: {writer.errorMessage()}",
        )
        return None

    # memo: 最終同期時刻を用いてAPIリクエストする。
    # そこで得られたデータは全てローカルキャッシュにUPSERTする。

    # FIXME: 一旦差分のことは考えないで毎回全件取得する
    BATCH_SIZE = 5000  # Number of features to fetch in each batch
    count = 0
    while True:
        # Fetch features in batches
        features = api.qgis_vector.get_features(
            vector_id=vector_id,
            limit=BATCH_SIZE,
            offset=count * BATCH_SIZE,
        )
        print(f"Fetched {len(features)} features from server.")

        for feature in features:
            qgsfeature = QgsFeature()
            # Set geometry
            g = QgsGeometry()
            g.fromWkb(feature["qgishub_wkb"])
            qgsfeature.setGeometry(g)

            # Set attributes
            qgsfeature.setFields(new_fields)
            qgsfeature["qgishub_id"] = feature["qgishub_id"]
            for name in fields.names():
                qgsfeature[name] = feature["properties"][name]

            # Set feature ID and validity
            qgsfeature.setValid(True)
            # 地物を書き込み
            writer.addFeature(qgsfeature)

        if len(features) < BATCH_SIZE:
            break
        count += 1

    del writer


def get_cached_layer(vector_id: str) -> QgsVectorLayer:
    """Retrieve a cached QgsVectorLayer by vector ID."""
    cache_dir = get_cache_dir()
    cache_file = os.path.join(cache_dir, f"{vector_id}.gpkg")
    layer = QgsVectorLayer(cache_file, "cache", "ogr")
    if layer.isValid():
        return layer
    else:
        QgsApplication.messageLog().logMessage(f"Cache layer {vector_id} is not valid.")
        return None
