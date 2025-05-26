from dataclasses import dataclass
from typing import Dict, List, Literal, Optional

from .client import ApiClient


@dataclass
class QgishubVector:
    id: str
    name: str
    uri: str
    type: Literal["POINT", "LINESTRING", "POLYGON"]
    projectId: str


# extends QgishubVector
@dataclass
class QgishubVectorReturnValue(QgishubVector):
    extent: List[float]
    count: int
    columns: Dict[str, str]
    userId: str = ""
    organizationId: str = ""
    role: Literal["ADMIN", "OWNER", "MEMBER", "NONE"] = "NONE"


def get_vectors(project_id: str) -> List[QgishubVector]:
    """
    Get a list of vectors for a specific project

    Args:
        project_id: Project ID

    Returns:
        List of QgishubVector objects
    """
    try:
        response = ApiClient.get(f"/project/{project_id}/vector")

        vectors = []
        for vector_data in response:
            vectors.append(
                QgishubVector(
                    id=vector_data.get("id", ""),
                    name=vector_data.get("name", ""),
                    uri=vector_data.get("uri", ""),
                    type=vector_data.get("type", "POINT"),
                    projectId=project_id,
                )
            )

        return vectors
    except Exception as e:
        print(f"Error fetching vectors for project {project_id}: {str(e)}")
        return []


def get_vector(project_id: str, vector_id: str) -> Optional[QgishubVectorReturnValue]:
    """
    Get details for a specific vector

    Args:
        project_id: Project ID
        vector_id: Vector ID

    Returns:
        QgishubVectorReturnValue object or None if not found
    """
    try:
        response = ApiClient.get(f"/vector/{vector_id}")

        if not response:
            return None

        return QgishubVectorReturnValue(
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
            role=response.get("role", ""),
        )

    except Exception as e:
        print(f"Error fetching vector {vector_id} for project {project_id}: {str(e)}")
        return None


@dataclass
class AddVectorOptions:
    name: str
    type: Literal["POINT", "LINESTRING", "POLYGON"]


def add_vector(
    project_id: str, add_vector_options: AddVectorOptions
) -> Optional[QgishubVector]:
    """
    Add a new vector to a project

    Args:
        project_id: Project ID
        add_vector_options: Options for the new vector

    Returns:
        QgishubVector object or None if creation failed
    """
    try:
        response = ApiClient.post(
            f"/project/{project_id}/vector",
            {"name": add_vector_options.name, "type": add_vector_options.type},
        )

        if not response:
            return None

        return QgishubVector(
            id=response.get("id", ""),
            name=response.get("name", ""),
            uri=response.get("uri", ""),
            type=response.get("type", "POINT"),
            projectId=project_id,
        )
    except Exception as e:
        print(f"Error adding vector to project {project_id}: {str(e)}")
        return None


def delete_vector(project_id: str, vector_id: str) -> bool:
    """
    Delete a vector from a project

    Args:
        project_id: Project ID
        vector_id: Vector ID

    Returns:
        True if successful, False otherwise
    """
    try:
        ApiClient.delete(f"/vector/{vector_id}")
        return True
    except Exception as e:
        print(f"Error deleting vector {vector_id}: {str(e)}")
        return False


@dataclass
class UpdateVectorOptions:
    name: str


def update_vector(
    project_id: str, vector_id: str, update_vector_options: UpdateVectorOptions
):
    try:
        ApiClient.patch(
            f"/vector/{vector_id}",
            {"name": update_vector_options.name},
        )
    except Exception as e:
        print(f"Error updating vector to project {project_id}: {str(e)}")
        return None
