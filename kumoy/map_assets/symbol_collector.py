"""シンボルからファイル参照を収集し、スプライト用画像を生成する"""

import os
from dataclasses import dataclass, field

from qgis.core import (
    QgsApplication,
    QgsProject,
    QgsRenderContext,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QImage


@dataclass
class SymbolFileRef:
    """シンボルレイヤーが参照するファイル"""

    original_path: str  # 元の絶対パス
    zip_name: str  # ZIP内ファイル名 ({symbolLayerID}.{ext})


@dataclass
class CollectedAssets:
    """プロジェクトから収集したアセット"""

    file_refs: list[SymbolFileRef] = field(default_factory=list)
    symbol_images: dict[str, QImage] = field(default_factory=dict)


def _get_file_path_from_symbol_layer(symbol_layer) -> str:
    """シンボルレイヤーからファイルパスを取得する。対応していない場合は空文字を返す。"""
    # QgsSvgMarkerSymbolLayer, QgsRasterMarkerSymbolLayer
    if hasattr(symbol_layer, "path"):
        return symbol_layer.path() or ""

    # QgsSVGFillSymbolLayer
    if hasattr(symbol_layer, "svgFilePath"):
        return symbol_layer.svgFilePath() or ""

    # QgsRasterFillSymbolLayer
    if hasattr(symbol_layer, "imageFilePath"):
        return symbol_layer.imageFilePath() or ""

    return ""


def _resolve_svg_path(path: str) -> str:
    """SVGパスを絶対パスに解決する。
    QGISのSVGサーチパスを考慮して相対パスを解決する。
    """
    if os.path.isabs(path) and os.path.isfile(path):
        return path

    # QGISのSVGサーチパスから探す
    for svg_dir in QgsApplication.svgPaths():
        full_path = os.path.join(svg_dir, path)
        if os.path.isfile(full_path):
            return full_path

    return path


def collect_assets(project: QgsProject) -> CollectedAssets:
    """プロジェクト内の全シンボルからファイル参照とスプライト画像を収集する。

    Args:
        project: QGISプロジェクト

    Returns:
        CollectedAssets: 収集したファイル参照とスプライト画像
    """
    result = CollectedAssets()
    seen_paths: dict[str, str] = {}  # original_path -> zip_name (重複排除)
    render_context = QgsRenderContext()

    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue

        renderer = layer.renderer()
        if renderer is None:
            continue

        for symbol in renderer.symbols(render_context):
            for i in range(symbol.symbolLayerCount()):
                sl = symbol.symbolLayer(i)
                sl_id = sl.id()

                # ファイルパス収集
                raw_path = _get_file_path_from_symbol_layer(sl)
                if raw_path and not raw_path.startswith(("http://", "https://")):
                    resolved = _resolve_svg_path(raw_path)
                    if os.path.isfile(resolved) and resolved not in seen_paths:
                        ext = os.path.splitext(resolved)[1]  # .svg, .png etc.
                        zip_name = f"{sl_id}{ext}"
                        seen_paths[resolved] = zip_name
                        result.file_refs.append(
                            SymbolFileRef(
                                original_path=resolved,
                                zip_name=zip_name,
                            )
                        )

                # スプライト画像生成
                if sl_id not in result.symbol_images:
                    image = symbol.asImage(QSize(64, 64))
                    if image and not image.isNull():
                        result.symbol_images[sl_id] = image

    return result
