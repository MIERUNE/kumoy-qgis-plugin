"""ZIPアーカイブ作成"""

import io
import zipfile

from .symbol_collector import SymbolFileRef

MAX_ZIP_SIZE = 10 * 1024 * 1024  # 10MB


def build_asset_zip(file_refs: list[SymbolFileRef]) -> bytes:
    """収集したファイルからZIPアーカイブを作成する。

    Args:
        file_refs: SymbolFileRefのリスト

    Returns:
        ZIPアーカイブのバイト列

    Raises:
        Exception: ZIPサイズが10MBを超過した場合
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for ref in file_refs:
            zf.write(ref.original_path, ref.zip_name)

    data = buf.getvalue()
    if len(data) > MAX_ZIP_SIZE:
        raise Exception(
            f"Asset ZIP size ({len(data)} bytes) exceeds the maximum limit of {MAX_ZIP_SIZE} bytes"
        )
    return data
