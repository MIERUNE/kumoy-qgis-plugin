"""ラスタ(COG)のローカルキャッシュ。

COG は immutable（rasterId が同じなら中身は変わらない）ため、ベクタのような差分
同期は不要で、「ローカルに無ければ署名付き URL でダウンロードし、在ればそれを使う」
だけで足りる。この単純さがベクタ側との最大の違い。

純粋なファイル＋ダウンロード操作に閉じ、UI（進捗ダイアログ・QMessageBox）は持た
ない。進捗・中断は呼び出し側のコールバックで受け取る。
"""

import os
import shutil
from typing import Optional

from qgis.core import QgsApplication

from .. import api, download
from .size import dir_total_size, files_total_size


def _get_cache_dir() -> str:
    """キャッシュファイルを格納するディレクトリを返す（無ければ作成）。"""
    setting_dir = QgsApplication.qgisSettingsDirPath()
    cache_dir = os.path.join(setting_dir, "kumoygis", "local_cache", "rasters")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def get_cache_path(raster_id: str) -> str:
    """raster_id に対応するキャッシュファイルのパスを返す（存在は問わない）。"""
    return os.path.join(_get_cache_dir(), f"{raster_id}.tif")


def is_cached(raster_id: str) -> bool:
    return os.path.exists(get_cache_path(raster_id))


def sync_local_cache(
    raster_id: str,
    progress_callback: Optional[download.ProgressCallback] = None,
    is_canceled: Optional[download.IsCanceledCallback] = None,
) -> str:
    """COG がローカルに無ければダウンロードし、キャッシュファイルのパスを返す。

    既にキャッシュ済みならネットワークアクセスせず即座にパスを返す（描画時に
    プロバイダが clone されるたびに呼ばれても安いことが重要）。

    Raises:
        download.DownloadCanceled: 中断要求があった場合。
        Exception: URL 取得・ダウンロード失敗時。
    """
    cache_path = get_cache_path(raster_id)
    if os.path.exists(cache_path):
        return cache_path

    url = api.raster.get_download_url(raster_id)

    # 途中失敗・中断で壊れた .tif を掴ませないよう、一旦 .part に落としてから
    # 完成時のみリネームする。download_to_file 自体も失敗時に書きかけを消すが、
    # ここでも本物のキャッシュパスを最後まで作らないことで二重に守る。
    part_path = f"{cache_path}.part"
    download.download_to_file(url, part_path, progress_callback, is_canceled)
    os.replace(part_path, cache_path)
    return cache_path


def store(raster_id: str, src_path: str) -> str:
    """手元にある COG ファイルをキャッシュへ取り込み、キャッシュパスを返す。

    アップロード直後など「S3 上の実体と同一のファイル」が既にローカルにある場合、
    これで取り込んでおけば以降の sync_local_cache はダウンロードせずに済む。
    COG は immutable なのでこの同一性が崩れることはない。

    src_path は移動により消費される（アップロード後の一時ファイルを想定）。
    tempdir とキャッシュディレクトリは別ファイルシステムのことがあるため、
    ダウンロード時と同じく .part 経由で原子的に確定させる。
    """
    cache_path = get_cache_path(raster_id)
    part_path = f"{cache_path}.part"
    shutil.move(src_path, part_path)
    os.replace(part_path, cache_path)
    return cache_path


def get_cache_size(raster_id: str) -> int:
    """Return the raster's cache size in bytes (0 when not cached).

    Covers the same file set as clear(): the .tif plus its in-progress .part.
    """
    cache_path = get_cache_path(raster_id)
    candidates = (cache_path, f"{cache_path}.part")
    # Existence is the caller's concern: files_total_size expects paths that
    # exist, and .tif / .part rarely coexist.
    return files_total_size(p for p in candidates if os.path.isfile(p))


def get_total_cache_size() -> int:
    """Return the total size in bytes of all cached raster files."""
    return dir_total_size(_get_cache_dir())


def clear(raster_id: str) -> bool:
    """特定ラスタのキャッシュを削除する。全て消せたら True。"""
    cache_path = get_cache_path(raster_id)
    success = True
    for f in (cache_path, f"{cache_path}.part"):
        if os.path.exists(f):
            try:
                os.unlink(f)
            except OSError:
                success = False
    return success


def clear_all() -> bool:
    """全ラスタキャッシュを削除する。全て消せたら True。"""
    cache_dir = _get_cache_dir()
    success = True
    # Subdirectories too: clear_all must cover everything dir_total_size counts.
    for entry in list(os.scandir(cache_dir)):
        try:
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path)
            else:
                os.unlink(entry.path)
        except OSError:
            success = False
    return success
