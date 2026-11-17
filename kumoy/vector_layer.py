from qgis.core import (
    QgsSimpleFillSymbolLayer,
    QgsSimpleLineSymbolLayer,
    QgsSimpleMarkerSymbolLayer,
    QgsSingleSymbolRenderer,
    QgsSymbol,
    QgsUnitTypes,
    QgsVectorLayer,
)

from .. import i18n
from . import constants
from .api.models import Vector, VectorDetail
from .provider.dataprovider import prime_vector


def vector_uri(vector: Vector) -> str:
    return (
        f"project_id={vector.projectId};"
        f"vector_id={vector.id};"
        f"vector_name={vector.name};"
        f"vector_type={vector.type};"
    )


def create_vector_layer(vector: Vector) -> QgsVectorLayer:
    """Open a Kumoy vector as a layer. Raises RuntimeError when invalid.

    Pass a VectorDetail when you have one: without a local cache the provider
    then needs no metadata request.
    """
    if isinstance(vector, VectorDetail):
        prime_vector(vector)
    layer = QgsVectorLayer(vector_uri(vector), vector.name, constants.DATA_PROVIDER_KEY)
    if not layer.isValid():
        # The layer does not copy its provider's error
        provider = layer.dataProvider()
        error = provider.error() if provider is not None else layer.error()
        error_msg = error.summary() or i18n.tr("Unknown error")
        raise RuntimeError(
            i18n.tr("Failed to create Kumoy layer: {}").format(error_msg)
        )

    # kumoy_id is assigned by the server, so keep it out of edit forms
    field_idx = layer.fields().indexOf("kumoy_id")
    if field_idx >= 0:
        config = layer.editFormConfig()
        config.setReadOnly(field_idx, True)
        layer.setEditFormConfig(config)

    return layer


def apply_pixel_based_style(layer: QgsVectorLayer) -> None:
    """Replace the default millimeter-based symbol with a pixel-based one."""
    symbol = QgsSymbol.defaultSymbol(layer.geometryType())
    if not symbol:
        return

    if symbol.symbolLayerCount() > 0:
        symbol_layer = symbol.symbolLayer(0)
        if isinstance(symbol_layer, QgsSimpleMarkerSymbolLayer):
            symbol_layer.setSize(5.0)
            symbol_layer.setSizeUnit(QgsUnitTypes.RenderPixels)
            symbol_layer.setStrokeWidth(1.0)
            symbol_layer.setStrokeWidthUnit(QgsUnitTypes.RenderPixels)
            symbol_layer.setOffsetUnit(QgsUnitTypes.RenderPixels)
        elif isinstance(symbol_layer, QgsSimpleLineSymbolLayer):
            symbol_layer.setWidth(2.0)
            symbol_layer.setWidthUnit(QgsUnitTypes.RenderPixels)
            symbol_layer.setOffsetUnit(QgsUnitTypes.RenderPixels)
        elif isinstance(symbol_layer, QgsSimpleFillSymbolLayer):
            symbol_layer.setStrokeWidth(1.0)
            symbol_layer.setStrokeWidthUnit(QgsUnitTypes.RenderPixels)
            symbol_layer.setOffsetUnit(QgsUnitTypes.RenderPixels)

    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    layer.triggerRepaint()
