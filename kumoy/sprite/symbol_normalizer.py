"""Map保存時にシンボルレイヤーのaspectRatioを明示化する処理。
Webでレンダリングする際、常にアスペクト比がわかっている必要があるが
デフォルトだとQgs-Xmlにアスペクト比が乗らないので、fixedAspectRatioを明示的にセットする
"""

from qgis.core import (
    QgsProject,
    QgsRasterMarkerSymbolLayer,
    QgsReadWriteContext,
    QgsRenderContext,
    QgsSvgMarkerSymbolLayer,
    QgsSymbol,
    QgsVectorLayer,
)
from qgis.PyQt.QtXml import QDomDocument

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

        # providerType() also works for unresolved layers, which have no provider
        if layer.providerType() != DATA_PROVIDER_KEY:
            continue

        renderer = layer.renderer()
        if renderer is None:
            continue

        for symbol in renderer.symbols(render_context):
            _pin_aspect_ratio_recursive(symbol)

        if not layer.isValid():
            _write_renderer_to_original_xml(layer, project)


def _write_renderer_to_original_xml(layer: QgsVectorLayer, project: QgsProject) -> None:
    """Carry the pinned renderer over to an unresolved layer's saved XML.

    QGIS writes an invalid layer back from the XML it was read from, so changes
    made to its renderer in memory would otherwise be dropped on write().
    """
    doc = QDomDocument()
    # The return type of setContent() differs between PyQt5 and PyQt6, so an
    # unparsable XML is detected by the missing element below instead
    doc.setContent(layer.originalXmlProperties())
    old_renderer = doc.documentElement().firstChildElement("renderer-v2")
    if old_renderer.isNull():
        return

    context = QgsReadWriteContext()
    context.setPathResolver(project.pathResolver())
    doc.documentElement().replaceChild(
        layer.renderer().save(doc, context), old_renderer
    )
    layer.setOriginalXmlProperties(doc.toString())
