import datetime
import os
from typing import Callable, Optional

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

from .. import api
from ..constants import LOG_CATEGORY
from .settings import delete_last_updated, get_last_updated, store_last_updated


def _get_cache_dir() -> str:
    """Return the directory where cache files are stored.
    data_type: subdirectory name maps or vectors"""
    setting_dir = QgsApplication.qgisSettingsDirPath()
    cache_dir = os.path.join(setting_dir, "kumoygis", "local_cache", "vectors")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _adjust_columns(vlayer: QgsVectorLayer, fields: QgsFields):
    """レイヤーのカラムをサーバーのスキーマに合わせて追加・削除する"""
    # サーバーに存在しないカラムをキャッシュから削除
    for cache_colname in vlayer.fields().names():
        if cache_colname == "kumoy_id":
            continue
        if fields.indexOf(cache_colname) == -1:
            vlayer.deleteAttribute(vlayer.fields().indexOf(cache_colname))

    # サーバーだけに存在するカラムをキャッシュに追加
    for name in fields.names():
        if vlayer.fields().indexOf(name) == -1:
            vlayer.addAttribute(QgsField(name, fields[name].type()))


def _fetch_and_add_features(
    vector_id: str,
    fields: QgsFields,
    add_feature_fn: Callable[[QgsFeature], None],
    progress_callback: Optional[Callable[[int], None]] = None,
):
    """サーバーから全地物をバッチ取得し、add_feature_fnで追加する"""
    BATCH_SIZE = 5000
    after_id = None
    processed_features = 0
    while True:
        features = api.qgis_vector.get_features(
            vector_id=vector_id,
            limit=BATCH_SIZE,
            after_id=after_id,
        )

        for feature in features:
            qgsfeature = QgsFeature()
            g = QgsGeometry()
            g.fromWkb(feature["kumoy_wkb"])
            qgsfeature.setGeometry(g)

            qgsfeature.setFields(fields)
            for name in fields.names():
                if name == "kumoy_id":
                    qgsfeature["kumoy_id"] = feature["kumoy_id"]
                else:
                    qgsfeature[name] = feature["properties"][name]

            qgsfeature.setValid(True)
            add_feature_fn(qgsfeature)

            if progress_callback is not None:
                processed_features += 1
                progress_callback(processed_features)

        if len(features) < BATCH_SIZE:
            break

        after_id = features[-1]["kumoy_id"]


def _create_new_cache(
    cache_file: str,
    vector_id: str,
    fields: QgsFields,
    geometry_type: QgsWkbTypes.GeometryType,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> str:
    """
    新規にキャッシュファイルを作成する

    Returns:
        updated_at: 最終更新日時
    """
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.layerOptions = ["FID=kumoy_id"]
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

    _fetch_and_add_features(
        vector_id, fields, lambda f: writer.addFeature(f), progress_callback
    )
    del writer

    return updated_at


def _update_existing_cache(cache_file: str, fields: QgsFields, diff: dict) -> str:
    """
    既存のキャッシュファイルを更新する

    Returns:
        updated_at: 最終更新日時
    """

    vlayer = QgsVectorLayer(cache_file, "temp", "ogr")
    vlayer.startEditing()

    _adjust_columns(vlayer, fields)

    updated_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    should_deleted_fids = diff["deletedRows"] + list(
        map(lambda rec: rec["kumoy_id"], diff["updatedRows"])
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
                g.fromWkb(feature["kumoy_wkb"])
                qgsfeature.setGeometry(g)

                # Set attributes
                qgsfeature.setFields(fields)

                for name in fields.names():
                    if name == "kumoy_id":
                        qgsfeature["kumoy_id"] = feature["kumoy_id"]
                    else:
                        qgsfeature[name] = feature["properties"][name]

                # Set feature ID and validity
                qgsfeature.setValid(True)
                vlayer.addFeature(qgsfeature)

    vlayer.commitChanges()
    return updated_at


def _truncate_cache(cache_file: str) -> bool:
    """キャッシュファイルのレコードを全て削除する。
    Returns True if successful, False otherwise.
    """
    vlayer = QgsVectorLayer(cache_file, "temp", "ogr")
    if not vlayer.isValid():
        return False
    vlayer.startEditing()
    fids = vlayer.allFeatureIds()
    if len(fids) > 0:
        vlayer.deleteFeatures(fids)
    return vlayer.commitChanges()


def _repopulate_cache(
    cache_file: str,
    vector_id: str,
    fields: QgsFields,
    geometry_type: QgsWkbTypes.GeometryType,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> str:
    """
    既存のキャッシュファイルの内容を全て削除し、サーバーから再取得して格納する

    Returns:
        updated_at: 最終更新日時
    """
    vlayer = QgsVectorLayer(cache_file, "temp", "ogr")
    if not vlayer.isValid():
        # フォールバック: ファイル削除を試行し新規作成する
        try:
            os.unlink(cache_file)
        except OSError:
            raise Exception(f"Cannot open or delete cache file: {cache_file}")
        return _create_new_cache(
            cache_file, vector_id, fields, geometry_type, progress_callback
        )

    vlayer.startEditing()

    _adjust_columns(vlayer, fields)

    # 全地物を削除
    fids = vlayer.allFeatureIds()
    if len(fids) > 0:
        vlayer.deleteFeatures(fids)

    # memo: ページングによりレコードを逐次取得していくが、取得中にレコードの更新があった際に
    # 正しく差分を取得するために、逐次取得開始前の時刻をlast_updatedとする
    updated_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    # サーバーから全地物を取得して追加
    _fetch_and_add_features(
        vector_id,
        vlayer.fields(),
        lambda f: vlayer.addFeature(f),
        progress_callback,
    )

    vlayer.commitChanges()
    return updated_at


def sync_local_cache(
    vector_id: str,
    fields: QgsFields,
    geometry_type: QgsWkbTypes.GeometryType,
    progress_callback: Optional[Callable[[int], None]] = None,
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

    # 不整合チェック: タイムスタンプあり・ファイルなし
    if last_updated is not None and not os.path.exists(cache_file):
        delete_last_updated(vector_id)
        last_updated = None

    if not os.path.exists(cache_file):
        # 新規キャッシュファイルを作成
        updated_at = _create_new_cache(
            cache_file,
            vector_id,
            fields,
            geometry_type,
            progress_callback=progress_callback,
        )
    elif last_updated is None:
        # ファイルあり・タイムスタンプなし（キャッシュクリア後、または不整合）
        # → サーバーから全件再取得
        updated_at = _repopulate_cache(
            cache_file,
            vector_id,
            fields,
            geometry_type,
            progress_callback=progress_callback,
        )
    else:
        # 既存キャッシュファイルを差分更新
        try:
            diff = api.qgis_vector.get_diff(vector_id, last_updated)
            updated_at = _update_existing_cache(cache_file, fields, diff)
        except api.error.AppError as e:
            if e.error == "MAX_DIFF_COUNT_EXCEEDED":
                QgsMessageLog.logMessage(
                    f"Diff for vector {vector_id} is too large, repopulating cache.",
                    LOG_CATEGORY,
                    Qgis.Info,
                )
                updated_at = _repopulate_cache(
                    cache_file,
                    vector_id,
                    fields,
                    geometry_type,
                    progress_callback=progress_callback,
                )
            else:
                raise e

    store_last_updated(vector_id, updated_at)


def get_layer(vector_id: str) -> QgsVectorLayer:
    """Retrieve a cached QgsVectorLayer by vector ID."""
    cache_dir = _get_cache_dir()
    cache_file = os.path.join(cache_dir, f"{vector_id}.gpkg")

    layer = QgsVectorLayer(cache_file, "cache", "ogr")

    if layer.isValid():
        return layer
    else:
        QgsMessageLog.logMessage(
            f"Cache layer {vector_id} is not valid.", LOG_CATEGORY, Qgis.Info
        )
        return None


def clear_all() -> bool:
    """全てのキャッシュGPKGファイルのレコードを削除する。
    Returns True if all caches were truncated successfully.
    """
    cache_dir = _get_cache_dir()
    success = True

    for filename in os.listdir(cache_dir):
        if not filename.endswith(".gpkg"):
            continue
        file_path = os.path.join(cache_dir, filename)
        if not _truncate_cache(file_path):
            QgsMessageLog.logMessage(
                f"Failed to truncate cache file: {file_path}",
                LOG_CATEGORY,
                Qgis.Info,
            )
            success = False
        vector_id = filename[:-5]  # strip .gpkg
        delete_last_updated(vector_id)

    return success


def clear(vector_id: str) -> bool:
    """指定ベクターのキャッシュレコードを全て削除する。
    Returns True if successful, False otherwise.
    """
    cache_dir = _get_cache_dir()
    cache_file = os.path.join(cache_dir, f"{vector_id}.gpkg")

    success = True
    if os.path.exists(cache_file):
        success = _truncate_cache(cache_file)
        if not success:
            QgsMessageLog.logMessage(
                f"Failed to truncate cache file: {cache_file}",
                LOG_CATEGORY,
                Qgis.Info,
            )

    delete_last_updated(vector_id)
    return success
