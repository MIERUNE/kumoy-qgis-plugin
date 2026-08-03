"""添付ファイルのローカルキャッシュ。

添付は immutable（attachmentId が同じなら中身は変わらない。差し替えは削除＋新規
作成としてサーバ側で強制される）ため、ラスタ同様に差分同期は不要で「ローカルに
無ければ署名付き URL でダウンロードし、在ればそれを使う」だけで足りる。

QGIS 標準の Attachment（External Resource）ウィジェットに画像を見せるのが目的
なので、キャッシュのファイル名は属性値（``{attachmentId}.{ext}``）そのままにする。
拡張子が保たれるので QGIS 側が形式を判定できる。

純粋なファイル＋ダウンロード操作に閉じ、UI は持たない。
"""

import os
import re
from typing import Optional, Tuple

from qgis.core import QgsApplication

from .. import api, download

# 属性値の形式。想定外の文字列でキャッシュパスを組ませない（パストラバーサル防止）。
_VALUE_PATTERN = re.compile(
    r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
    r"\.([A-Za-z0-9]+)$"
)

# vector_id も同様にパスの一部になるため検証する。
_UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class InvalidAttachmentValue(Exception):
    """属性値が ``{attachmentId}.{ext}`` の形式でない。"""


def parse_value(value: str) -> Optional[Tuple[str, str]]:
    """属性値を ``(attachment_id, ext)`` に分解する。形式が違えば None。"""
    if not isinstance(value, str):
        return None
    match = _VALUE_PATTERN.match(value)
    if match is None:
        return None
    return match.group(1).lower(), match.group(2).lower()


def _get_cache_dir(vector_id: str) -> str:
    """Vector 単位のキャッシュディレクトリを返す（無ければ作成）。

    Vector ごとに分けることで、Vector のキャッシュ破棄と添付の破棄を揃えられる。
    """
    if not _UUID_PATTERN.match(vector_id):
        raise InvalidAttachmentValue(f"Invalid vector id: {vector_id}")
    setting_dir = QgsApplication.qgisSettingsDirPath()
    cache_dir = os.path.join(
        setting_dir, "kumoygis", "local_cache", "attachments", vector_id
    )
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def get_root_dir() -> str:
    """全 Vector の添付キャッシュのルート。"""
    setting_dir = QgsApplication.qgisSettingsDirPath()
    root = os.path.join(setting_dir, "kumoygis", "local_cache", "attachments")
    os.makedirs(root, exist_ok=True)
    return root


def get_cache_path(vector_id: str, value: str) -> str:
    """属性値に対応するキャッシュファイルのパスを返す（存在は問わない）。

    Raises:
        InvalidAttachmentValue: 属性値が想定の形式でない場合。
    """
    parsed = parse_value(value)
    if parsed is None:
        raise InvalidAttachmentValue(f"Invalid attachment value: {value}")
    attachment_id, ext = parsed
    return os.path.join(_get_cache_dir(vector_id), f"{attachment_id}.{ext}")


def is_cached(vector_id: str, value: str) -> bool:
    try:
        return os.path.exists(get_cache_path(vector_id, value))
    except InvalidAttachmentValue:
        return False


def sync_local_cache(
    vector_id: str,
    value: str,
    progress_callback: Optional[download.ProgressCallback] = None,
    is_canceled: Optional[download.IsCanceledCallback] = None,
) -> str:
    """添付がローカルに無ければダウンロードし、キャッシュファイルのパスを返す。

    既にキャッシュ済みならネットワークアクセスせず即座にパスを返す（フォーム表示の
    たびに呼ばれても安いことが重要）。

    Raises:
        InvalidAttachmentValue: 属性値が想定の形式でない場合。
        download.DownloadCanceled: 中断要求があった場合。
        Exception: URL 取得・ダウンロード失敗時。
    """
    cache_path = get_cache_path(vector_id, value)
    if os.path.exists(cache_path):
        return cache_path

    attachment_id, _ = parse_value(value)
    url = api.attachment.get_download_url(vector_id, attachment_id)

    # 途中失敗・中断で壊れた画像を掴ませないよう、一旦 .part に落としてから
    # 完成時のみリネームする。
    part_path = f"{cache_path}.part"
    download.download_to_file(url, part_path, progress_callback, is_canceled)
    os.replace(part_path, cache_path)
    return cache_path


def store(vector_id: str, value: str, src_path: str) -> str:
    """手元のファイルをキャッシュへ取り込み、キャッシュパスを返す。

    アップロード直後は「S3 上の実体と同一のファイル」がローカルにあるので、
    これで取り込んでおけば以降の sync_local_cache はダウンロードせずに済む。
    添付は immutable なのでこの同一性が崩れることはない。

    src_path はコピー元として残す（ユーザーが選んだ元ファイルを消さない）。
    """
    cache_path = get_cache_path(vector_id, value)
    part_path = f"{cache_path}.part"
    with open(src_path, "rb") as src, open(part_path, "wb") as dst:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            dst.write(chunk)
    os.replace(part_path, cache_path)
    return cache_path


def clear(vector_id: str) -> bool:
    """特定 Vector の添付キャッシュを削除する。全て消せたら True。"""
    try:
        cache_dir = _get_cache_dir(vector_id)
    except InvalidAttachmentValue:
        return False

    success = True
    for filename in os.listdir(cache_dir):
        try:
            os.unlink(os.path.join(cache_dir, filename))
        except OSError:
            success = False
    if success:
        try:
            os.rmdir(cache_dir)
        except OSError:
            # 空にできていれば十分。ディレクトリが残っても害はない
            pass
    return success


def clear_all() -> bool:
    """全 Vector の添付キャッシュを削除する。全て消せたら True。"""
    root = get_root_dir()
    success = True
    for vector_dir in os.listdir(root):
        path = os.path.join(root, vector_dir)
        if not os.path.isdir(path):
            continue
        for filename in os.listdir(path):
            try:
                os.unlink(os.path.join(path, filename))
            except OSError:
                success = False
        try:
            os.rmdir(path)
        except OSError:
            pass
    return success
