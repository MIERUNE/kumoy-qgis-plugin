from typing import Dict, List, Tuple

from qgis.core import QgsMapLayer, QgsProject, QgsRasterLayer, QgsVectorLayer


def analyze_layer_maplibre_compatibility() -> Tuple[List[str], List[str]]:
    """
    Analyze current QGIS project layers for MapLibre compatibility.

    Returns:
        Tuple of (compatible_layers, incompatible_layers) where each is a list
        of strings in the format "layer_name (provider_type)"
    """
    project = QgsProject.instance()
    layers: Dict[str, QgsMapLayer] = project.mapLayers()

    compatible_layers = []
    incompatible_layers = []

    for map_layer in layers.values():
        layer_name = map_layer.name()
        provider_type = map_layer.dataProvider().name()

        # Check if layer is compatible with MapLibre based on provider type
        is_compatible = False

        if isinstance(map_layer, QgsVectorLayer):
            if provider_type == "qgishub":
                is_compatible = True
        if isinstance(map_layer, QgsRasterLayer):
            if provider_type == "wms":
                source = map_layer.dataProvider().dataSourceUri()
                if "type=xyz" in source.lower():
                    is_compatible = True

        if is_compatible:
            compatible_layers.append(f"{layer_name} ({provider_type})")
        else:
            incompatible_layers.append(f"{layer_name} ({provider_type})")

    return compatible_layers, incompatible_layers
