"""添付ファイルのアップロード。

サムネイル生成はクライアント側の責務（サーバに画像処理基盤を持たない）。QImage で
長辺 512px の WebP に再エンコードする。再エンコードにより EXIF も実質的に除去される
（原本には残る点に注意）。

「Attachment 行の作成 → S3 への PUT → 属性値の書き込み」のうち、ここが担うのは
前二つ。属性値の書き込みは呼び出し側（External Resource ウィジェット、または
プラグインのアクション）が行い、そこでサーバ側の遷移ルール検証を通る。

UI は持たない。進捗・中断は呼び出し側のコールバックで受け取る。
"""

import os
import tempfile
from typing import Optional

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QBuffer, QByteArray
from qgis.PyQt.QtGui import QImage

from ..pyqt_version import (
    Q_IODEVICE_OPEN_MODE,
    QT_ASPECT_RATIO_MODE,
    QT_TRANSFORMATION_MODE,
)
from . import api, local_cache
from .upload import presigned

# 許可する拡張子と MIME。サーバ側の allowlist と一致させる。
EXT_TO_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}

# サーバに渡す ext は正規化する（jpeg は jpg に寄せる）。
_EXT_ALIAS = {"jpeg": "jpg"}

THUMBNAIL_MIME = "image/webp"
_THUMBNAIL_MAX_EDGE = 512
_THUMBNAIL_QUALITY = 75

# 1ファイルの上限。サーバ側の制限と一致させる（超過は PUT 前にここで弾く）。
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


class UnsupportedAttachmentError(Exception):
    """拡張子が許可されていない。"""


class AttachmentTooLargeError(Exception):
    """ファイルサイズが上限を超えている。"""


def normalized_ext(file_path: str) -> str:
    """ファイルパスから、サーバに渡す拡張子を求める。

    Raises:
        UnsupportedAttachmentError: 許可されていない拡張子の場合。
    """
    ext = os.path.splitext(file_path)[1].lstrip(".").lower()
    if ext not in EXT_TO_MIME:
        raise UnsupportedAttachmentError(ext)
    return _EXT_ALIAS.get(ext, ext)


def create_thumbnail_bytes(file_path: str) -> bytes:
    """長辺 512px の WebP サムネイルを生成する。

    Raises:
        Exception: 画像として読めない場合。
    """
    image = QImage(file_path)
    if image.isNull():
        raise Exception(f"Cannot read image: {file_path}")

    # 長辺のみ指定して縦横比を保つ。元が 512px 以下なら拡大しない
    longest = max(image.width(), image.height())
    if longest > _THUMBNAIL_MAX_EDGE:
        image = image.scaled(
            _THUMBNAIL_MAX_EDGE,
            _THUMBNAIL_MAX_EDGE,
            QT_ASPECT_RATIO_MODE.KeepAspectRatio,
            QT_TRANSFORMATION_MODE.SmoothTransformation,
        )

    byte_array = QByteArray()
    buffer = QBuffer(byte_array)
    buffer.open(Q_IODEVICE_OPEN_MODE.WriteOnly)
    if not image.save(buffer, "WEBP", _THUMBNAIL_QUALITY):
        raise Exception("Failed to encode thumbnail as WebP")
    buffer.close()

    return bytes(byte_array)


def upload(
    vector_id: str,
    kumoy_id: int,
    vector_column_id: str,
    file_path: str,
    progress_callback: Optional[presigned.ProgressCallback] = None,
    is_canceled: Optional[presigned.IsCanceledCallback] = None,
) -> str:
    """添付をアップロードし、属性カラムに格納すべき値を返す。

    戻り値を属性値として書き込んで初めて「地物に付いた」状態になる。PUT 後に
    属性値の書き込みまで到達しなくても、S3 のゴミと Attachment 行が残るだけで
    表示上の不整合は起きない。

    Raises:
        UnsupportedAttachmentError: 許可されていない拡張子。
        AttachmentTooLargeError: 上限超過。
        presigned.UploadCanceled: 中断要求があった場合。
        Exception: サムネイル生成・API・アップロード失敗時。
    """
    ext = normalized_ext(file_path)
    size = os.path.getsize(file_path)
    if size <= 0 or size > MAX_ATTACHMENT_BYTES:
        raise AttachmentTooLargeError(str(size))

    thumbnail = create_thumbnail_bytes(file_path)

    upload_info = api.attachment.create_attachment(
        vector_id=vector_id,
        kumoy_id=kumoy_id,
        vector_column_id=vector_column_id,
        ext=ext,
        bytes=size,
        thumbnail_bytes=len(thumbnail),
    )

    presigned.upload_file_to_presigned_put(
        upload_info.upload_url,
        file_path,
        EXT_TO_MIME[ext],
        progress_callback,
        is_canceled,
    )

    # サムネイルはメモリ上の小さなバイト列だが、原本と同じ presigned PUT で送る
    # （POST ポリシーではないので multipart にする必要がない）。
    _put_bytes(upload_info.thumbnail_upload_url, thumbnail)

    # 直後は「S3 上の実体と同一のファイル」が手元にあるので、キャッシュへ取り込んで
    # おけば以降のフォーム表示でダウンロードが走らない。
    try:
        local_cache.attachment.store(vector_id, upload_info.value, file_path)
    except Exception:
        # キャッシュ取り込みの失敗はアップロードの成否に影響しない（次回 fetch で回収）
        pass

    return upload_info.value


def _put_bytes(url: str, data: bytes) -> None:
    """メモリ上のバイト列を presigned PUT で送る（一時ファイル経由）。

    ``upload_file_to_presigned_put`` はストリーミング送信のため QIODevice を要求
    する。サムネイルは数十 KB なので一時ファイル経由でも安く、送信経路を原本と
    一本化できる（Qt バージョン差による chunked 送信問題も避けられる）。
    """
    fd, temp_path = tempfile.mkstemp(
        suffix=".webp", dir=QgsApplication.qgisSettingsDirPath()
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        presigned.upload_file_to_presigned_put(url, temp_path, THUMBNAIL_MIME)
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
