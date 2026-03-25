"""QGS XML内のファイルパスを相対パスに書き換える"""

from .symbol_collector import SymbolAsset


def rewrite_paths(qgs_xml: str, assets: list[SymbolAsset]) -> str:
    """QGS XML内のファイルパスを相対パスに書き換える。

    元の絶対パスを `./assets/{zip_name}` に置換する。

    Args:
        qgs_xml: QGS XMLの文字列
        assets: SymbolAssetのリスト

    Returns:
        書き換え後のQGS XML文字列
    """
    for asset in assets:
        if not asset.original_path:
            continue
        relative_path = f"./assets/{asset.zip_name}"
        qgs_xml = qgs_xml.replace(asset.original_path, relative_path)
        qgs_xml = qgs_xml.replace(asset.original_path.replace("/", "\\"), relative_path)

    return qgs_xml
