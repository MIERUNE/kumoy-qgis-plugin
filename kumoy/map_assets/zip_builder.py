"""ZIPアーカイブ作成"""

import io
import zipfile

from .symbol_collector import SymbolAsset

MAX_ZIP_SIZE = 10 * 1024 * 1024  # 10MB


def build_asset_zip(assets: list[SymbolAsset]) -> bytes:
    """収集したファイルからZIPアーカイブを作成する。

    Args:
        assets: SymbolAssetのリスト

    Returns:
        ZIPアーカイブのバイト列

    Raises:
        Exception: ZIPサイズが10MBを超過した場合
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for asset in assets:
            if asset.original_path:
                zf.write(asset.original_path, asset.zip_name)

    data = buf.getvalue()
    if len(data) > MAX_ZIP_SIZE:
        raise Exception(
            f"Asset ZIP size ({len(data)} bytes) exceeds the maximum limit of {MAX_ZIP_SIZE} bytes"
        )
    return data
