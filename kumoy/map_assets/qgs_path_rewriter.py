"""QGS XML内のファイルパスを相対パスに書き換える"""

from .symbol_collector import SymbolFileRef


def rewrite_paths(qgs_xml: str, file_refs: list[SymbolFileRef]) -> str:
    """QGS XML内のファイルパスを相対パスに書き換える。

    元の絶対パスを `./assets/{zip_name}` に置換する。

    Args:
        qgs_xml: QGS XMLの文字列
        file_refs: SymbolFileRefのリスト

    Returns:
        書き換え後のQGS XML文字列
    """
    for ref in file_refs:
        relative_path = f"./assets/{ref.zip_name}"
        # 元のパスをそのまま置換
        qgs_xml = qgs_xml.replace(ref.original_path, relative_path)
        # Windows形式のバックスラッシュパスも置換
        qgs_xml = qgs_xml.replace(ref.original_path.replace("/", "\\"), relative_path)

    return qgs_xml
