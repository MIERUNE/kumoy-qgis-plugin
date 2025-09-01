from dataclasses import dataclass
from typing import List, Optional

from .client import ApiClient


@dataclass
class Project:
    id: str
    name: str
    organizationId: str = ""
    createdAt: str = ""
    updatedAt: str = ""


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
                organizationId=organization_id,
                createdAt=project.get("createdAt", ""),
                updatedAt=project.get("updatedAt", ""),
            )
        )

    return projects


def get_project(project_id: str) -> Optional[Project]:
    """
    Get details for a specific project

    Args:
        project_id: Project ID

    Returns:
        Project object or None if not found
    """
    response = ApiClient.get(f"/project/{project_id}")

    # Extract organization ID from nested organization object
    organization = response.get("organization", {})
    organization_id = organization.get("id", "") if organization else ""

    return Project(
        id=response.get("id", ""),
        name=response.get("name", ""),
        organizationId=organization_id,
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
    )


def create_project(
    organization_id: str, name: str, description: str = ""
) -> Optional[Project]:
    """
    Create a new project

    Args:
        organization_id: Organization ID
        name: Project name
        description: Project description

    Returns:
        Project object or None if creation failed
    """

    response = ApiClient.post(
        "/project",
        {
            "name": name,
            "description": description,
            "organizationId": organization_id,
        },
    )

    return Project(
        id=response.get("id", ""),
        name=response.get("name", ""),
        organizationId=response.get("organizationId", ""),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
    )


def update_project(
    project_id: str, name: str, description: str = ""
) -> Optional[Project]:
    """
    Update an existing project

    Args:
        project_id: Project ID
        name: New project name
        description: New project description

    Returns:
        Updated Project object or None if update failed
    """

    response = ApiClient.put(
        f"/project/{project_id}",
        {
            "name": name,
            "description": description,
        },
    )

    return Project(
        id=response.get("id", ""),
        name=response.get("name", ""),
        organizationId=response.get("organizationId", ""),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
    )


def delete_project(project_id: str) -> bool:
    """
    Delete a project

    Args:
        project_id: Project ID

    Returns:
        True if successful, False otherwise
    """
    ApiClient.delete(f"/project/{project_id}")
