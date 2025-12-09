from dataclasses import dataclass
from typing import List

from .client import ApiClient


@dataclass
class Layer:
    id: str
    name: str
    type: str
    projectId: str = ""
    source: str = ""
    createdAt: str = ""
    updatedAt: str = ""


def get_layers_by_project(project_id: str) -> List[Layer]:
    """
    Get a list of layers for a specific project

    Args:
        project_id: Project ID

    Returns:
        List of Layer objects
    """
    response = ApiClient.get(f"/project/{project_id}/layers")

    layers = []
    for layer_data in response.get("layers", []):
        layers.append(
            Layer(
                id=layer_data.get("id", ""),
                name=layer_data.get("name", ""),
                type=layer_data.get("type", ""),
                projectId=project_id,
                source=layer_data.get("source", ""),
                createdAt=layer_data.get("createdAt", ""),
                updatedAt=layer_data.get("updatedAt", ""),
            )
        )

    return layers


def get_layer(layer_id: str) -> Layer:
    """
    Get details for a specific layer

    Args:
        layer_id: Layer ID

    Returns:
        Layer object or None if not found
    """
    response = ApiClient.get(f"/layer/{layer_id}")
    return Layer(
        id=response.get("id", ""),
        name=response.get("name", ""),
        type=response.get("type", ""),
        projectId=response.get("projectId", ""),
        source=response.get("source", ""),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
    )


def create_layer(
    project_id: str, name: str, layer_type: str, source: str = ""
) -> Layer:
    """
    Create a new layer

    Args:
        project_id: Project ID
        name: Layer name
        layer_type: Layer type (vector, raster, etc.)
        source: Layer source

    Returns:
        Layer object or None if creation failed
    """
    data = {
        "name": name,
        "type": layer_type,
        "projectId": project_id,
        "source": source,
    }

    response = ApiClient.post("/layer", data)

    return Layer(
        id=response.get("id", ""),
        name=response.get("name", ""),
        type=response.get("type", ""),
        projectId=response.get("projectId", ""),
        source=response.get("source", ""),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
    )


def update_layer(
    layer_id: str, name: str, layer_type: str = "", source: str = ""
) -> Layer:
    """
    Update an existing layer

    Args:
        layer_id: Layer ID
        name: New layer name
        layer_type: New layer type
        source: New layer source

    Returns:
        Updated Layer object or None if update failed
    """

    data = {
        "name": name,
    }

    if layer_type:
        data["type"] = layer_type

    if source:
        data["source"] = source

    response = ApiClient.put(f"/layer/{layer_id}", data)

    return Layer(
        id=response.get("id", ""),
        name=response.get("name", ""),
        type=response.get("type", ""),
        projectId=response.get("projectId", ""),
        source=response.get("source", ""),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
    )


def delete_layer(layer_id: str):
    """
    Delete a layer

    Args:
        layer_id: Layer ID

    Returns:
        True if successful, False otherwise
    """
    ApiClient.delete(f"/layer/{layer_id}")
