import datetime
import os
from typing import Callable, Optional

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFeature,
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
from .size import dir_total_size, files_total_size


def _get_cache_dir() -> str:
    """Return the directory where cache files are stored.
    data_type: subdirectory name maps or vectors"""
    setting_dir = QgsApplication.qgisSettingsDirPath()
    cache_dir = os.path.join(setting_dir, "kumoygis", "local_cache", "vectors")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


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

    after_id = None  # 1回のバッチで最後に取得したkumoy_idを保持する
    processed_features = 0
    while True:
        # Fetch features in batches
        features = api.qgis_vector.get_features(
            vector_id=vector_id,
            after_id=after_id,
        )

        for feature in features:
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
            # 地物を書き込み
            writer.addFeature(qgsfeature)

            if progress_callback is not None:
                processed_features += 1
                progress_callback(processed_features)

        BATCH_SIZE = 5000  # 1回のバッチで取得する最大レコード数。API仕様として固定値
        if len(features) < BATCH_SIZE:
            # 取得終了
            break

        # Update after_id for the next batch
        after_id = features[-1]["kumoy_id"]
    del writer

    return updated_at


def _columns_match(cache_file: str, fields: QgsFields) -> bool:
    """
    キャッシュGPKGの物理カラム順とサーバー側 fields のカラム順を比較する。
    kumoy_id は FID として特別扱いされるので比較対象から除外する。
    一致すれば True、不一致なら False。GPKGがロードできない場合も False。
    """
    vlayer = QgsVectorLayer(cache_file, "tmp", "ogr")
    if not vlayer.isValid():
        del vlayer
        return False

    cache_names = [n for n in vlayer.fields().names() if n != "kumoy_id"]
    server_names = [n for n in fields.names() if n != "kumoy_id"]
    del vlayer

    return cache_names == server_names


def _recreate_cache(
    cache_file: str,
    vector_id: str,
    fields: QgsFields,
    geometry_type: QgsWkbTypes.GeometryType,
    progress_callback: Optional[Callable[[int], None]],
    reason: str,
) -> str:
    """既存キャッシュを破棄して新規作成する"""
    QgsMessageLog.logMessage(
        f"Recreating cache for vector {vector_id}: {reason}",
        LOG_CATEGORY,
        Qgis.Info,
    )
    if not clear(vector_id):
        # clear() がファイルロック等で失敗した場合、上書き作成も失敗するので
        # 部分的な再生成で壊れた状態にしないように中断する
        raise Exception(
            f"Failed to clear cache for vector {vector_id} "
            "(file may be locked by another process)"
        )
    return _create_new_cache(
        cache_file,
        vector_id,
        fields,
        geometry_type,
        progress_callback=progress_callback,
    )


def _update_existing_cache(cache_file: str, fields: QgsFields, diff: dict) -> str:
    """
    既存のキャッシュファイルに差分を適用する。
    カラム集合・順序の整合は呼び出し側で担保する前提（不一致なら再生成パスに入る）。

    Returns:
        updated_at: 最終更新日時
    """

    vlayer = QgsVectorLayer(cache_file, "temp", "ogr")
    vlayer.startEditing()

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
    if last_updated is None and os.path.exists(cache_file):
        # キャッシュファイルが存在するが、最終更新日時が設定されていない場合
        # 不整合が生じているので既存ファイルを削除する
        clear(vector_id)
    if last_updated is not None and not os.path.exists(cache_file):
        # キャッシュファイルが存在しないが、最終更新日時が設定されている場合
        # 不整合が生じているので最終更新日時を削除する
        delete_last_updated(vector_id)
        last_updated = None

    if os.path.exists(cache_file):
        # 既存キャッシュファイルを更新（ファイルが存在するのでlast_updatedはNoneではないはず）
        if last_updated is None:
            raise Exception(
                "Inconsistent state: cache file exists but last_updated is None"
            )

        if not _columns_match(cache_file, fields):
            # 物理カラム順とサーバー順が一致しない → 再生成
            updated_at = _recreate_cache(
                cache_file,
                vector_id,
                fields,
                geometry_type,
                progress_callback,
                reason="cache column order differs from server",
            )
        else:
            try:
                # memo: この処理は失敗しうる（e.g. 差分が大きすぎる場合）
                diff = api.qgis_vector.get_diff(vector_id, last_updated)
                # 差分取得でエラーがなかった場合は、得られた差分をキャッシュに適用する
                updated_at = _update_existing_cache(cache_file, fields, diff)
            except api.error.AppError as e:
                if e.error == "MAX_DIFF_COUNT_EXCEEDED":
                    updated_at = _recreate_cache(
                        cache_file,
                        vector_id,
                        fields,
                        geometry_type,
                        progress_callback,
                        reason="MAX_DIFF_COUNT_EXCEEDED",
                    )
                else:
                    raise
    else:
        # 新規キャッシュファイルを作成
        updated_at = _create_new_cache(
            cache_file,
            vector_id,
            fields,
            geometry_type,
            progress_callback=progress_callback,
        )

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
    """Clear all cached GPKG files. Returns True if all files were deleted successfully."""

    cache_dir = _get_cache_dir()
    success = True

    # Remove all files in cache directory
    for filename in os.listdir(cache_dir):
        file_path = os.path.join(cache_dir, filename)
        try:
            os.unlink(file_path)
            if filename.endswith(".gpkg"):
                project_id = filename.split(".gpkg")[0]
                delete_last_updated(project_id)
        except PermissionError as e:
            # Ignore Permission denied error and continue
            QgsMessageLog.logMessage(
                f"Ignored file access error: {e}",
                LOG_CATEGORY,
                Qgis.Info,
            )
            success = False  # Flag unsucceed deletion
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Unexpected error for {file_path}: {e}",
                LOG_CATEGORY,
                Qgis.Critical,
            )
            success = False  # Flag unsucceed

    return success


def get_cache_size(vector_id: str) -> Optional[int]:
    """Return the vector's cache size in bytes (None when not cached).

    Covers the same file set as clear(): the GPKG plus its SQLite side files.
    """
    cache_file = os.path.join(_get_cache_dir(), f"{vector_id}.gpkg")
    return files_total_size(
        (
            cache_file,
            f"{cache_file}-shm",
            f"{cache_file}-wal",
            f"{cache_file}-journal",
        )
    )


def get_total_cache_size() -> Optional[int]:
    """Return the total size in bytes of all cached vector files (None when none)."""
    return dir_total_size(_get_cache_dir())


def clear(vector_id: str) -> bool:
    """Clear cache for a specific vector.
    Returns True if all files were deleted successfully, False otherwise.
    """
    cache_dir = _get_cache_dir()
    cache_file = os.path.join(cache_dir, f"{vector_id}.gpkg")
    gpkg_shm_file = f"{cache_file}-shm"
    gpkg_wal_file = f"{cache_file}-wal"
    gpkg_journal_file = f"{cache_file}-journal"

    files_to_remove = [cache_file, gpkg_shm_file, gpkg_wal_file, gpkg_journal_file]
    success = True

    # Remove cache file if it exists
    for f in files_to_remove:
        if os.path.exists(f):
            try:
                os.unlink(f)
            except PermissionError as e:
                QgsMessageLog.logMessage(
                    f"Ignored file access error for {f}: {e}", LOG_CATEGORY, Qgis.Info
                )
                success = False  # Flag unsucceed deletion
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Unexpected error for {f}: {e}",
                    LOG_CATEGORY,
                    Qgis.Critical,
                )
                success = False
    # ファイル削除に失敗した状態で last_updated を消すと、GPKGは残るのに
    # タイムスタンプだけ消える不整合状態になり、以後の同期が
    # 'cache file exists but last_updated is None' で固まる。
    # 削除が全件成功した場合のみタイムスタンプも消す。
    if success:
        delete_last_updated(vector_id)

    return success
