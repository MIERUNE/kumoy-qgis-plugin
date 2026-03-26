"""ZIPアーカイブ作成"""

import io
import zipfile

from .symbol_collector import FileAsset

MAX_ZIP_SIZE = 10 * 1024 * 1024  # 10MB


def build_asset_zip(files: list[FileAsset]) -> bytes:
    """収集したファイルからZIPアーカイブを作成する。

    ZIP内ファイル名は {symbolLayerID}.{ext} となる。

    Args:
        files: FileAssetのリスト

    Returns:
        ZIPアーカイブのバイト列

    Raises:
        Exception: ZIPサイズが10MBを超過した場合
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for asset in files:
            zip_name = f"{asset.symbol_layer_id}{asset.ext}"
            zf.write(asset.original_path, zip_name)

    data = buf.getvalue()
    if len(data) > MAX_ZIP_SIZE:
        raise Exception(
            f"Asset ZIP size ({len(data)} bytes) exceeds the maximum limit of {MAX_ZIP_SIZE} bytes"
        )
    return data
