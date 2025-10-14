from dataclasses import dataclass
from typing import List, Literal, Optional

from .client import ApiClient


@dataclass
class Project:
    id: str
    name: str
    description: str
    createdAt: str
    updatedAt: str
    vectorCount: int
    mapCount: int
    storageUnitSum: float
    thumbnailImageUrl: str


def get_projects_by_organization(organization_id: str) -> List[Project]:
    """
    Get a list of projects for a specific organization

    Args:
        organization_id: Organization ID

    Returns:
        List of Project objects
    """
    response = ApiClient.get(f"/organization/{organization_id}/projects")
    projects = []
    for project in response:
        projects.append(
            Project(
                id=project.get("id", ""),
                name=project.get("name", ""),
                description=project.get("description", ""),
                createdAt=project.get("createdAt", ""),
                updatedAt=project.get("updatedAt", ""),
                vectorCount=project.get("vectorCount", 0),
                mapCount=project.get("mapCount", 0),
                storageUnitSum=project.get("storageUnitSum", 0.0),
                thumbnailImageUrl=project.get("thumbnailImageUrl", ""),
            )
        )

    return projects


@dataclass
class ProjectDetail:
    id: str
    name: str
    description: str
    createdAt: str
    updatedAt: str
    organizationId: str
    storageUnitSum: float
    thumbnailImageUrl: str
    vectorCount: int
    mapCount: int


@dataclass
class ProjectDetailWithRole(ProjectDetail):
    role: Literal["ADMIN", "OWNER", "MEMBER"]


def get_project(project_id: str) -> ProjectDetailWithRole:
    """
    Get details for a specific project

    Args:
        project_id: Project ID

    Returns:
        Project object or None if not found
    """
    response = ApiClient.get(f"/project/{project_id}")

    return ProjectDetailWithRole(
        id=response.get("id", ""),
        name=response.get("name", ""),
        description=response.get("description", ""),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
        organizationId=response.get("organization", {}).get("id", ""),
        storageUnitSum=response.get("storageUnitSum", 0.0),
        thumbnailImageUrl=response.get("thumbnailImageUrl"),
        vectorCount=response.get("vectorCount", 0),
        mapCount=response.get("mapCount", 0),
        role=response.get("role", "MEMBER"),
    )


def create_project(organization_id: str, name: str, description: str) -> ProjectDetail:
    """
    Create a new project

    Args:
        organization_id: Organization ID
        name: Project name

    Returns:
        Project object or None if creation failed
    """

    response = ApiClient.post(
        "/project",
        {
            "name": name,
            "organizationId": organization_id,
        },
    )

    return ProjectDetail(
        id=response.get("id", ""),
        name=response.get("name", ""),
        description=response.get("description", ""),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
        organizationId=response.get("organizationId", ""),
        storageUnitSum=response.get("storageUnitSum", 0.0),
        thumbnailImageUrl=response.get("thumbnailImageUrl"),
    )


def update_project(project_id: str, name: str, description: str) -> ProjectDetail:
    """
    Update an existing project

    Args:
        project_id: Project ID
        name: New project name

    Returns:
        Updated Project object or None if update failed
    """

    response = ApiClient.put(
        f"/project/{project_id}",
        {
            "name": name,
        },
    )

    return ProjectDetail(
        id=response.get("id", ""),
        name=response.get("name", ""),
        description=response.get("description", ""),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
        organizationId=response.get("organizationId", ""),
        storageUnitSum=response.get("storageUnitSum", 0.0),
        thumbnailImageUrl=response.get("thumbnailImageUrl"),
    )


def delete_project(project_id: str):
    """
    Delete a project

    Args:
        project_id: Project ID

    Returns:
        True if successful, False otherwise
    """
    ApiClient.delete(f"/project/{project_id}")
