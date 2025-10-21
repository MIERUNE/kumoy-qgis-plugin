from dataclasses import dataclass
from typing import Dict, List, Literal, Optional

from .client import ApiClient


@dataclass
class StratoVector:
    id: str
    name: str
    uri: str
    type: Literal["POINT", "LINESTRING", "POLYGON"]
    projectId: str


# extends StratoVector
@dataclass
class StratoVectorDetail(StratoVector):
    extent: List[float]
    count: int
    columns: Dict[str, str]
    userId: str = ""
    organizationId: str = ""
    role: Literal["ADMIN", "OWNER", "MEMBER"] = "MEMBER"


def get_vectors(project_id: str) -> List[StratoVector]:
    """
    Get a list of vectors for a specific project

    Args:
        project_id: Project ID

    Returns:
        List of StratoVector objects
    """
    response = ApiClient.get(f"/project/{project_id}/vector")
    vectors = []
    for vector_data in response:
        vectors.append(
            StratoVector(
                id=vector_data.get("id", ""),
                name=vector_data.get("name", ""),
                uri=vector_data.get("uri", ""),
                type=vector_data.get("type", "POINT"),
                projectId=project_id,
            )
        )

    return vectors


def get_vector(project_id: str, vector_id: str) -> StratoVectorDetail:
    """
    Get details for a specific vector

    Args:
        project_id: Project ID
        vector_id: Vector ID

    Returns:
        StratoVectorDetail object or None if not found
    """
    response = ApiClient.get(f"/vector/{vector_id}")

    return StratoVectorDetail(
        id=response.get("id", ""),
        name=response.get("name", ""),
        uri=response.get("uri", ""),
        type=response.get("type", "POINT"),
        projectId=project_id,
        extent=response.get("extent", []),
        count=response.get("count", 0),
        columns=response.get("columns", []),
        userId=response.get("userId", ""),
        organizationId=response.get("organizationId", ""),
        role=response.get("role", "MEMBER"),
    )


@dataclass
class AddVectorOptions:
    name: str
    type: Literal["POINT", "LINESTRING", "POLYGON"]


def add_vector(project_id: str, add_vector_options: AddVectorOptions) -> StratoVector:
    """
    Add a new vector to a project

    Args:
        project_id: Project ID
        add_vector_options: Options for the new vector

    Returns:
        StratoVector object or None if creation failed
    """
    response = ApiClient.post(
        f"/project/{project_id}/vector",
        {"name": add_vector_options.name, "type": add_vector_options.type},
    )

    return StratoVector(
        id=response.get("id", ""),
        name=response.get("name", ""),
        uri=response.get("uri", ""),
        type=response.get("type", "POINT"),
        projectId=project_id,
    )


def delete_vector(vector_id: str):
    """
    Delete a vector from a project

    Args:
        project_id: Project ID
        vector_id: Vector ID

    Returns:
        True if successful, False otherwise
    """
    ApiClient.delete(f"/vector/{vector_id}")


@dataclass
class UpdateVectorOptions:
    name: str


def update_vector(
    project_id: str, vector_id: str, update_vector_options: UpdateVectorOptions
) -> StratoVector:
    """
    Update an existing vector

    Args:
        project_id: Project ID
        vector_id: Vector ID
        update_vector_options: Update options

    Returns:
        StratoVector object or None if update failed
    """
    response = ApiClient.put(
        f"/vector/{vector_id}",
        {"name": update_vector_options.name},
    )
    return StratoVector(
        id=response.get("id", ""),
        name=response.get("name", ""),
        uri=response.get("uri", ""),
        type=response.get("type", "POINT"),
        projectId=project_id,
    )
