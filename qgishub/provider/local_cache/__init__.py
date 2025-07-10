import datetime
import os

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
from qgis.PyQt.QtCore import QVariant

from ... import api
from .settings import delete_last_updated, get_last_updated, store_last_updated


def _get_cache_dir() -> str:
    """Return the directory where cache files are stored."""
    setting_dir = QgsApplication.qgisSettingsDirPath()
    cache_dir = os.path.join(setting_dir, "qgishub", "local_cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _create_new_cache(
    cache_file: str,
    vector_id: str,
    fields: QgsFields,
    geometry_type: QgsWkbTypes.GeometryType,
) -> str:
    """
    新規にキャッシュファイルを作成する

    Returns:
        updated_at: 最終更新日時
    """
    new_fields = QgsFields(fields)  # ユーザー定義カラム
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

    # memo: ページングによりレコードを逐次取得していくが、取得中にレコードの更新があった際に
    # 正しく差分を取得するために、逐次取得開始前の時刻をlast_updatedとする
    updated_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    BATCH_SIZE = 5000  # Number of features to fetch in each batch
    count = 0
    after_id = None  # 1回のバッチで最後に取得したqgishub_idを保持する
    while True:
        # Fetch features in batches
        features = api.qgis_vector.get_features(
            vector_id=vector_id,
            limit=BATCH_SIZE,
            after_id=after_id,
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
            # 取得終了
            break

        # Update after_id for the next batch
        after_id = features[-1]["qgishub_id"]

        count += 1
    del writer

    return updated_at


def _update_existing_cache(
    cache_file: str, vector_id: str, fields: QgsFields, last_updated: str
) -> str:
    """
    既存のキャッシュファイルを更新する

    Returns:
        updated_at: 最終更新日時
    """
    new_fields = QgsFields(fields)  # ユーザー定義カラム
    new_fields.append(QgsField("qgishub_id", QVariant.Int))

    vlayer = QgsVectorLayer(cache_file, "temp", "ogr")
    # 最終同期時刻を用いてAPIリクエストして差分を取得する
    diff = api.qgis_vector.get_diff(vector_id, last_updated)
    updated_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    should_deleted_fids = diff["deletedRows"] + list(
        map(lambda rec: rec["qgishub_id"], diff["updatedRows"])
    )

    if len(should_deleted_fids) == 0 and len(diff["updatedRows"]) == 0:
        # No changes, do nothing
        pass
    else:
        vlayer.startEditing()

        # 削除された行と更新された行を全て削除する
        if len(should_deleted_fids) > 0:
            for fid in should_deleted_fids:
                # Delete features by fid
                feature = vlayer.getFeature(fid)
                if feature.isValid():
                    vlayer.deleteFeature(feature.id())

        # 更新された行を新たなレコードとして追加する
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

    return updated_at


def sync_local_cache(
    vector_id: str, fields: QgsFields, geometry_type: QgsWkbTypes.GeometryType
):
    """
    サーバー上のデータとローカルのキャッシュを同期する
    - キャッシュはGPKGを用いる
    - ローカルにGPKGが存在しなければ新規で作成する
    - この関数の実行時、サーバー上のデータとの差分を取得してローカルのキャッシュを更新する
    """
    cache_dir = _get_cache_dir()
    cache_file = os.path.join(cache_dir, f"{vector_id}.gpkg")

    last_updated = get_last_updated(vector_id)
    if last_updated is None and os.path.exists(cache_file):
        # キャッシュファイルが存在するが、最終更新日時が設定されていない場合
        # 不整合が生じているので既存ファイルを削除する
        os.remove(cache_file)
    if last_updated is not None and not os.path.exists(cache_file):
        # キャッシュファイルが存在しないが、最終更新日時が設定されている場合
        # 不整合が生じているので最終更新日時を削除する
        delete_last_updated(vector_id)
        last_updated = None

    if os.path.exists(cache_file):
        # 前回更新から一定時間経過していない場合は同期しない
        last_updated_dt = datetime.datetime.strptime(
            last_updated, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        if (now - last_updated_dt).total_seconds() < 1:  # 1秒以内の更新は無視
            return

        # 既存キャッシュファイルを更新
        updated_at = _update_existing_cache(cache_file, vector_id, fields, last_updated)
    else:
        # 新規キャッシュファイルを作成
        updated_at = _create_new_cache(cache_file, vector_id, fields, geometry_type)
        if updated_at is None:
            return

    store_last_updated(vector_id, updated_at)


LAYER_CACHE = {}


def get_cached_layer(vector_id: str) -> QgsVectorLayer:
    """Retrieve a cached QgsVectorLayer by vector ID."""
    if vector_id in LAYER_CACHE:
        return LAYER_CACHE[vector_id]

    cache_dir = _get_cache_dir()
    cache_file = os.path.join(cache_dir, f"{vector_id}.gpkg")
    layer = QgsVectorLayer(cache_file, "cache", "ogr")
    if layer.isValid():
        LAYER_CACHE[vector_id] = layer
        return layer
    else:
        QgsApplication.messageLog().logMessage(f"Cache layer {vector_id} is not valid.")
        return None
