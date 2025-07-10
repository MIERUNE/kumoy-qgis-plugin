import datetime
import os
from functools import lru_cache

from qgis.core import (
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
from qgis.PyQt.QtCore import QSettings, QVariant

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

    new_fields = QgsFields(fields)
    new_fields.append(QgsField("qgishub_id", QVariant.Int))

    last_updated = get_last_updated(vector_id)
    if last_updated is None and os.path.exists(cache_file):
        # キャッシュファイルが存在するが、最終更新日時が設定されていない場合
        # 不整合が生じているので既存ファイルを削除する
        os.remove(cache_file)

    if os.path.exists(cache_file):
        # memo: 最終同期時刻を用いてAPIリクエストする。
        # そこで得られたデータは全てローカルキャッシュにUPSERTする。
        # last_updatedが存在することは保証されている
        diff = api.qgis_vector.get_diff(vector_id, last_updated)

        should_deleted_fids = diff["deletedRows"] + list(
            map(lambda rec: rec["qgishub_id"], diff["updatedRows"])
        )

        if len(should_deleted_fids) == 0 and len(diff["updatedRows"]) == 0:
            # No changes, do nothing
            pass
        else:
            vlayer = QgsVectorLayer(cache_file, "temp", "ogr")
            vlayer.startEditing()

            if len(should_deleted_fids) > 0:
                for fid in should_deleted_fids:
                    # Delete features by fid
                    feature = vlayer.getFeature(fid)
                    if feature.isValid():
                        vlayer.deleteFeature(feature.id())

            if len(diff["updatedRows"]) > 0:
                # add features
                for feature in diff["updatedRows"]:
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
                    vlayer.addFeature(qgsfeature)

            vlayer.commitChanges()
            del vlayer

    else:
        # Create a new cache file
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

        BATCH_SIZE = 5000  # Number of features to fetch in each batch
        count = 0
        while True:
            # Fetch features in batches
            features = api.qgis_vector.get_features(
                vector_id=vector_id,
                limit=BATCH_SIZE,
                offset=count * BATCH_SIZE,
            )

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

    last_updated = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    store_last_updated(vector_id, last_updated)


@lru_cache(maxsize=128)
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


SETTING_GROUP = "/QGISHUB/local_cache"


def get_last_updated(vector_id: str) -> str:
    """
    Get the last updated timestamp for a vector ID from settings.
    Returns None if not found.
    """
    qsettings = QSettings()
    qsettings.beginGroup(SETTING_GROUP)
    value = qsettings.value(vector_id)
    qsettings.endGroup()
    return value


def store_last_updated(vector_id: str, timestamp: str):
    """
    Store the last updated timestamp for a vector ID in settings.
    """
    qsettings = QSettings()
    qsettings.beginGroup(SETTING_GROUP)
    qsettings.setValue(vector_id, timestamp)
    qsettings.endGroup()
