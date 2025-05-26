from dataclasses import dataclass
from typing import List, Optional

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
    try:
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
    except Exception as e:
        print(f"Error fetching layers for project {project_id}: {str(e)}")
        return []


def get_layer(layer_id: str) -> Optional[Layer]:
    """
    Get details for a specific layer

    Args:
        layer_id: Layer ID

    Returns:
        Layer object or None if not found
    """
    try:
        response = ApiClient.get(f"/layer/{layer_id}")

        if not response:
            return None

        return Layer(
            id=response.get("id", ""),
            name=response.get("name", ""),
            type=response.get("type", ""),
            projectId=response.get("projectId", ""),
            source=response.get("source", ""),
            createdAt=response.get("createdAt", ""),
            updatedAt=response.get("updatedAt", ""),
        )
    except Exception as e:
        print(f"Error fetching layer {layer_id}: {str(e)}")
        return None


def create_layer(
    project_id: str, name: str, layer_type: str, source: str = ""
) -> Optional[Layer]:
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
    try:
        data = {
            "name": name,
            "type": layer_type,
            "projectId": project_id,
            "source": source,
        }

        response = ApiClient.post("/layer", data)

        if not response:
            return None

        return Layer(
            id=response.get("id", ""),
            name=response.get("name", ""),
            type=response.get("type", ""),
            projectId=response.get("projectId", ""),
            source=response.get("source", ""),
            createdAt=response.get("createdAt", ""),
            updatedAt=response.get("updatedAt", ""),
        )
    except Exception as e:
        print(f"Error creating layer: {str(e)}")
        return None


def update_layer(
    layer_id: str, name: str, layer_type: str = "", source: str = ""
) -> Optional[Layer]:
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
    try:
        data = {
            "name": name,
        }

        if layer_type:
            data["type"] = layer_type

        if source:
            data["source"] = source

        response = ApiClient.patch(f"/layer/{layer_id}", data)

        if not response:
            return None

        return Layer(
            id=response.get("id", ""),
            name=response.get("name", ""),
            type=response.get("type", ""),
            projectId=response.get("projectId", ""),
            source=response.get("source", ""),
            createdAt=response.get("createdAt", ""),
            updatedAt=response.get("updatedAt", ""),
        )
    except Exception as e:
        print(f"Error updating layer {layer_id}: {str(e)}")
        return None


def delete_layer(layer_id: str) -> bool:
    """
    Delete a layer

    Args:
        layer_id: Layer ID

    Returns:
        True if successful, False otherwise
    """
    try:
        ApiClient.delete(f"/layer/{layer_id}")
        return True
    except Exception as e:
        print(f"Error deleting layer {layer_id}: {str(e)}")
        return False
