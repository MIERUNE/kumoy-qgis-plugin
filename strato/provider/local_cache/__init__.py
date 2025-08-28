import datetime
import os

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsMessageLog,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)

from ... import api
from ...constants import LOG_CATEGORY
from .settings import delete_last_updated, get_last_updated, store_last_updated


class MaxDiffCountExceededError(Exception):
    """Custom exception for when the diff count exceeds the maximum limit."""

    pass


def _get_cache_dir() -> str:
    """Return the directory where cache files are stored."""
    setting_dir = QgsApplication.qgisSettingsDirPath()
    cache_dir = os.path.join(setting_dir, "stratogis", "local_cache")
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
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.layerOptions = ["FID=strato_id"]
    options.driverName = "GPKG"
    options.fileEncoding = "UTF-8"

    writer = QgsVectorFileWriter.create(
        cache_file,
        fields,
        geometry_type,
        QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsProject.instance().transformContext(),
        options,
    )

    if writer.hasError() != QgsVectorFileWriter.NoError:
        QgsMessageLog.logMessage(
            f"Error creating cache file {cache_file}: {writer.errorMessage()}",
            LOG_CATEGORY,
            Qgis.Info,
        )
        raise Exception(
            f"Error creating cache file {cache_file}: {writer.errorMessage()}"
        )

    # memo: ページングによりレコードを逐次取得していくが、取得中にレコードの更新があった際に
    # 正しく差分を取得するために、逐次取得開始前の時刻をlast_updatedとする
    updated_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    BATCH_SIZE = 5000  # Number of features to fetch in each batch
    after_id = None  # 1回のバッチで最後に取得したstrato_idを保持する
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
            g.fromWkb(feature["strato_wkb"])
            qgsfeature.setGeometry(g)

            # Set attributes
            qgsfeature.setFields(fields)
            for name in fields.names():
                if name == "strato_id":
                    qgsfeature["strato_id"] = feature["strato_id"]
                else:
                    qgsfeature[name] = feature["properties"][name]

            # Set feature ID and validity
            qgsfeature.setValid(True)
            # 地物を書き込み
            writer.addFeature(qgsfeature)

        if len(features) < BATCH_SIZE:
            # 取得終了
            break

        # Update after_id for the next batch
        after_id = features[-1]["strato_id"]
    del writer

    return updated_at


def _update_existing_cache(
    cache_file: str, vector_id: str, fields: QgsFields, diff: dict
) -> str:
    """
    既存のキャッシュファイルを更新する

    Returns:
        updated_at: 最終更新日時
    """

    if vector_id in LAYER_CACHE:
        vlayer = LAYER_CACHE[vector_id]
    else:
        # キャッシュファイルが存在する場合は、QgsVectorLayerを作成してキャッシュを読み込む
        LAYER_CACHE[vector_id] = QgsVectorLayer(cache_file, "temp", "ogr")
        vlayer = LAYER_CACHE[vector_id]

    vlayer.startEditing()

    # サーバーに存在しないカラムをキャッシュから削除
    for cache_colname in vlayer.fields().names():
        if cache_colname == "strato_id":
            continue
        # キャッシュにはあるが、現在のサーバー上のカラムには存在しないキャッシュのカラムを削除
        if fields.indexOf(cache_colname) == -1:
            vlayer.deleteAttribute(vlayer.fields().indexOf(cache_colname))

    # サーバーだけに存在するカラムをキャッシュに追加
    for name in fields.names():
        if vlayer.fields().indexOf(name) == -1:
            vlayer.addAttribute(QgsField(name, fields[name].type()))

    updated_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    should_deleted_fids = diff["deletedRows"] + list(
        map(lambda rec: rec["strato_id"], diff["updatedRows"])
    )

    if len(should_deleted_fids) == 0 and len(diff["updatedRows"]) == 0:
        # No changes, do nothing
        pass
    else:
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
                g.fromWkb(feature["strato_wkb"])
                qgsfeature.setGeometry(g)

                # Set attributes
                qgsfeature.setFields(fields)

                for name in fields.names():
                    if name == "strato_id":
                        qgsfeature["strato_id"] = feature["strato_id"]
                    else:
                        qgsfeature[name] = feature["properties"][name]

                # Set feature ID and validity
                qgsfeature.setValid(True)
                vlayer.addFeature(qgsfeature)

    vlayer.commitChanges()
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
        # 既存キャッシュファイルを更新
        try:
            # memo: この処理は失敗しうる（e.g. 差分が大きすぎる場合）
            diff = api.qgis_vector.get_diff(vector_id, last_updated)
            # 差分取得でエラーがなかった場合は、得られた差分をキャッシュに適用する
            updated_at = _update_existing_cache(cache_file, vector_id, fields, diff)
        except MaxDiffCountExceededError:
            # 差分が大きすぎる場合はキャッシュファイルを削除して新規作成する
            QgsMessageLog.logMessage(
                f"Diff for vector {vector_id} is too large, recreating cache file.",
                LOG_CATEGORY,
                Qgis.Info,
            )
            os.remove(cache_file)
            updated_at = _create_new_cache(cache_file, vector_id, fields, geometry_type)
    else:
        # 新規キャッシュファイルを作成
        updated_at = _create_new_cache(cache_file, vector_id, fields, geometry_type)

    store_last_updated(vector_id, updated_at)


LAYER_CACHE = {}


def get_cached_layer(vector_id: str) -> QgsVectorLayer:
    """Retrieve a cached QgsVectorLayer by vector ID."""
    cache_dir = _get_cache_dir()
    cache_file = os.path.join(cache_dir, f"{vector_id}.gpkg")

    if vector_id not in LAYER_CACHE:
        LAYER_CACHE[vector_id] = QgsVectorLayer(cache_file, "cache", "ogr")

    layer = LAYER_CACHE[vector_id]
    if layer.isValid():
        return layer
    else:
        QgsMessageLog.logMessage(
            f"Cache layer {vector_id} is not valid.", LOG_CATEGORY, Qgis.Info
        )
        return None


def clear_all():
    """Clear cached GPKG files"""
    cache_dir = _get_cache_dir()
    # Remove all files in cache directory
    for filename in os.listdir(cache_dir):
        file_path = os.path.join(cache_dir, filename)
        os.unlink(file_path)

    global LAYER_CACHE
    for vector_id in list(LAYER_CACHE.keys()):
        del LAYER_CACHE[vector_id]
        delete_last_updated(vector_id)

    LAYER_CACHE.clear()


def clear(vector_id: str):
    """Clear cache for a specific vector."""
    cache_dir = _get_cache_dir()
    cache_file = os.path.join(cache_dir, f"{vector_id}.gpkg")
    gpkg_shm_file = f"{cache_file}-shm"
    gpkg_wal_file = f"{cache_file}-wal"
    gpkg_journal_file = f"{cache_file}-journal"

    # Remove cache file if it exists
    if os.path.exists(cache_file):
        os.unlink(cache_file)
    if os.path.exists(gpkg_shm_file):
        os.unlink(gpkg_shm_file)
    if os.path.exists(gpkg_wal_file):
        os.unlink(gpkg_wal_file)
    if os.path.exists(gpkg_journal_file):
        os.unlink(gpkg_journal_file)

    # Remove from in-memory cache
    global LAYER_CACHE
    if vector_id in LAYER_CACHE:
        del LAYER_CACHE[vector_id]

    # Delete last updated timestamp
    delete_last_updated(vector_id)
