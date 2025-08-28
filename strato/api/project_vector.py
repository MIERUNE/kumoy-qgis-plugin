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
class StratoVectorReturnValue(StratoVector):
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

    if response.get("error"):
        print(f"Error fetching vectors for project {project_id}: {response['error']}")
        return []

    vectors = []
    for vector_data in response["content"]:
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


def get_vector(project_id: str, vector_id: str) -> Optional[StratoVectorReturnValue]:
    """
    Get details for a specific vector

    Args:
        project_id: Project ID
        vector_id: Vector ID

    Returns:
        StratoVectorReturnValue object or None if not found
    """
    response = ApiClient.get(f"/vector/{vector_id}")
    if response.get("error"):
        print(
            f"Error fetching vector {vector_id} for project {project_id}: {response['error']}"
        )
        return None

    if not response["content"]:
        return None

    return StratoVectorReturnValue(
        id=response["content"].get("id", ""),
        name=response["content"].get("name", ""),
        uri=response["content"].get("uri", ""),
        type=response["content"].get("type", "POINT"),
        projectId=project_id,
        extent=response["content"].get("extent", []),
        count=response["content"].get("count", 0),
        columns=response["content"].get("columns", []),
        userId=response["content"].get("userId", ""),
        organizationId=response["content"].get("organizationId", ""),
        role=response["content"].get("role", "MEMBER"),
    )


@dataclass
class AddVectorOptions:
    name: str
    type: Literal["POINT", "LINESTRING", "POLYGON"]


def add_vector(
    project_id: str, add_vector_options: AddVectorOptions
) -> Optional[StratoVector]:
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

    if response.get("error"):
        print(f"Error adding vector to project {project_id}: {response['error']}")
        return None

    if not response["content"]:
        return None

    return StratoVector(
        id=response["content"].get("id", ""),
        name=response["content"].get("name", ""),
        uri=response["content"].get("uri", ""),
        type=response["content"].get("type", "POINT"),
        projectId=project_id,
    )


def delete_vector(project_id: str, vector_id: str) -> bool:
    """
    Delete a vector from a project

    Args:
        project_id: Project ID
        vector_id: Vector ID

    Returns:
        True if successful, False otherwise
    """
    response = ApiClient.delete(f"/vector/{vector_id}")

    if response.get("error"):
        print(f"Error deleting vector {vector_id}: {response['error']}")
        return False

    return True


@dataclass
class UpdateVectorOptions:
    name: str


def update_vector(
    project_id: str, vector_id: str, update_vector_options: UpdateVectorOptions
) -> Optional[StratoVector]:
    """
    Update an existing vector

    Args:
        project_id: Project ID
        vector_id: Vector ID
        update_vector_options: Update options

    Returns:
        StratoVector object or None if update failed
    """
    response = ApiClient.patch(
        f"/vector/{vector_id}",
        {"name": update_vector_options.name},
    )

    if response.get("error"):
        print(f"Error updating vector to project {project_id}: {response['error']}")
        return None

    if not response["content"]:
        return None

    return StratoVector(
        id=response["content"].get("id", ""),
        name=response["content"].get("name", ""),
        uri=response["content"].get("uri", ""),
        type=response["content"].get("type", "POINT"),
        projectId=project_id,
    )
