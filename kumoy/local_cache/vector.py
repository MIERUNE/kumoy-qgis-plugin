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


def _update_existing_cache(cache_file: str, fields: QgsFields, diff: dict) -> str:
    """
    既存のキャッシュファイルを更新する

    Returns:
        updated_at: 最終更新日時
    """

    vlayer = QgsVectorLayer(cache_file, "temp", "ogr")
    vlayer.startEditing()

    # サーバーに存在しないカラムをキャッシュから削除
    for cache_colname in vlayer.fields().names():
        if cache_colname == "kumoy_id":
            continue
        # キャッシュにはあるが、現在のサーバー上のカラムには存在しないキャッシュのカラムを削除
        if fields.indexOf(cache_colname) == -1:
            vlayer.deleteAttribute(vlayer.fields().indexOf(cache_colname))

    # サーバーだけに存在するカラムをキャッシュに追加
    for name in fields.names():
        if vlayer.fields().indexOf(name) == -1:
            vlayer.addAttribute(QgsField(name, fields[name].type()))

    # スキーマ調整後、vlayer.fields() の物理順序を確定させる
    vlayer.updateFields()

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

                # サーバーの columns 返却順に依存しないよう、既存 GPKG の物理順 (vlayer.fields()) を信頼する
                qgsfeature.setFields(vlayer.fields())

                for name in vlayer.fields().names():
                    if name == "kumoy_id":
                        qgsfeature["kumoy_id"] = feature["kumoy_id"]
                    else:
                        qgsfeature[name] = feature["properties"].get(name)

                # Set feature ID and validity
                qgsfeature.setValid(True)
                vlayer.addFeature(qgsfeature)

    vlayer.commitChanges()
    return updated_at


def _cache_can_incrementally_sync(cache_file: str, intended: QgsFields) -> bool:
    """既存 GPKG が intended の先頭一致なら、_update_existing_cache で末尾に
    新規カラムを追加するだけで intended と物理順を揃えられる(regen 不要)。

    True 例: cache=[kumoy_id, a, b], intended=[kumoy_id, a, b, c]
    False 例:
      - cache=[kumoy_id, c, a, b], intended=[kumoy_id, a, b, c]  (順序が違う)
      - cache=[kumoy_id, a, b, x], intended=[kumoy_id, a, b]      (削除)
      - cache=[kumoy_id, a, c],    intended=[kumoy_id, a, b, c]   (中間挿入)
    False の場合は呼び出し側で regen させる前提。
    """
    layer = QgsVectorLayer(cache_file, "check_columns", "ogr")
    if not layer.isValid():
        return False
    cache_names = list(layer.fields().names())
    intended_names = list(intended.names())
    del layer  # ファイルロックの解放
    if len(cache_names) > len(intended_names):
        return False
    return intended_names[: len(cache_names)] == cache_names


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
    - 既存GPKGのカラム順が intended と一致しない場合は、キャッシュをクリアして新規作成し直す
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

    # 既存キャッシュのカラム順が intended と乖離していて _update_existing_cache だけでは
    # 揃え直せない場合は、GPKG を作り直す(SQLite ではカラム順を後から並べ替えることが
    # 実用的にできないため、全件再ダウンロードで対応)。
    # 末尾に新規カラムを追加するだけで揃うケース(=addAttributes 直後の同セッション)では
    # regen は走らない。主に regen が走るのは:
    #   (a) pre-change 時代の GPKG (順序未保証) からの移行 — 初回 1 回のみ
    #   (b) addAttributes で末尾追加した GPKG を、API ソート順に揃え直す次セッション
    if os.path.exists(cache_file) and not _cache_can_incrementally_sync(
        cache_file, fields
    ):
        QgsMessageLog.logMessage(
            f"Cache columns out of sync for vector {vector_id}, recreating cache file.",
            LOG_CATEGORY,
            Qgis.Info,
        )
        clear(vector_id)
        last_updated = None

    if os.path.exists(cache_file):
        # 既存キャッシュファイルを更新（ファイルが存在するのでlast_updatedはNoneではないはず）
        if last_updated is None:
            raise Exception(
                "Inconsistent state: cache file exists but last_updated is None"
            )
        try:
            # memo: この処理は失敗しうる（e.g. 差分が大きすぎる場合）
            diff = api.qgis_vector.get_diff(vector_id, last_updated)
            # 差分取得でエラーがなかった場合は、得られた差分をキャッシュに適用する
            updated_at = _update_existing_cache(cache_file, fields, diff)
        except api.error.AppError as e:
            if e.error == "MAX_DIFF_COUNT_EXCEEDED":
                # 差分が大きすぎる場合はキャッシュファイルを削除して新規作成する
                QgsMessageLog.logMessage(
                    f"Diff for vector {vector_id} is too large, recreating cache file.",
                    LOG_CATEGORY,
                    Qgis.Info,
                )
                clear(vector_id)
                updated_at = _create_new_cache(
                    cache_file,
                    vector_id,
                    fields,
                    geometry_type,
                    progress_callback=progress_callback,
                )
            else:
                raise e
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
    # Delete last updated timestamp
    delete_last_updated(vector_id)

    return success
