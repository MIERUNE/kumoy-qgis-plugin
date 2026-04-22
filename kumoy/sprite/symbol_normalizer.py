"""Map保存時にシンボルレイヤーのaspectRatioを明示化する処理。
Webでレンダリングする際、常にアスペクト比がわかっている必要があるが
デフォルトだとQgs-Xmlにアスペクト比が乗らないので、fixedAspectRatioを明示的にセットする
"""

from qgis.core import (
    QgsProject,
    QgsRasterMarkerSymbolLayer,
    QgsRenderContext,
    QgsSvgMarkerSymbolLayer,
    QgsSymbol,
    QgsVectorLayer,
)

from ..constants import DATA_PROVIDER_KEY


def _pin_aspect_ratio_recursive(symbol: QgsSymbol) -> None:
    for symbol_layer in symbol.symbolLayers():
        if isinstance(
            symbol_layer, (QgsRasterMarkerSymbolLayer, QgsSvgMarkerSymbolLayer)
        ):
            if symbol_layer.fixedAspectRatio() == 0:
                symbol_layer.setFixedAspectRatio(symbol_layer.defaultAspectRatio())

        sub_symbol = symbol_layer.subSymbol()
        if sub_symbol is not None:
            _pin_aspect_ratio_recursive(sub_symbol)


def pin_fixed_aspect_ratios(project: QgsProject) -> None:
    """Kumoyレイヤーのsymbol layerのうち、fixedAspectRatio == 0（自動）のものを
    defaultAspectRatioの値で明示的に固定する。

    対象: QgsRasterMarkerSymbolLayer, QgsSvgMarkerSymbolLayer、および
    MarkerLineなどのsub-symbol内の該当レイヤー。
    """
    render_context = QgsRenderContext()

    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue

        if layer.dataProvider().name() != DATA_PROVIDER_KEY:
            continue

        renderer = layer.renderer()
        if renderer is None:
            continue

        for symbol in renderer.symbols(render_context):
            _pin_aspect_ratio_recursive(symbol)
