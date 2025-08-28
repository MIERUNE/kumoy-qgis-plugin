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

    if response.get("error"):
        print(
            f"Error fetching projects for organization {organization_id}: {response['error']}"
        )
        return []

    projects = []
    for project in response["content"]:
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

    if response.get("error"):
        print(f"Error fetching project {project_id}: {response['error']}")
        return None

    if not response["content"]:
        return None

    # Extract organization ID from nested organization object
    organization = response["content"].get("organization", {})
    organization_id = organization.get("id", "") if organization else ""

    return Project(
        id=response["content"].get("id", ""),
        name=response["content"].get("name", ""),
        organizationId=organization_id,
        createdAt=response["content"].get("createdAt", ""),
        updatedAt=response["content"].get("updatedAt", ""),
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
    data = {
        "name": name,
        "description": description,
        "organizationId": organization_id,
    }

    response = ApiClient.post("/project", data)

    if response.get("error"):
        print(f"Error creating project: {response['error']}")
        return None

    if not response["content"]:
        return None

    return Project(
        id=response["content"].get("id", ""),
        name=response["content"].get("name", ""),
        organizationId=response["content"].get("organizationId", ""),
        createdAt=response["content"].get("createdAt", ""),
        updatedAt=response["content"].get("updatedAt", ""),
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
    data = {
        "name": name,
        "description": description,
    }

    response = ApiClient.patch(f"/project/{project_id}", data)

    if response.get("error"):
        print(f"Error updating project {project_id}: {response['error']}")
        return None

    if not response["content"]:
        return None

    return Project(
        id=response["content"].get("id", ""),
        name=response["content"].get("name", ""),
        organizationId=response["content"].get("organizationId", ""),
        createdAt=response["content"].get("createdAt", ""),
        updatedAt=response["content"].get("updatedAt", ""),
    )


def delete_project(project_id: str) -> bool:
    """
    Delete a project

    Args:
        project_id: Project ID

    Returns:
        True if successful, False otherwise
    """
    response = ApiClient.delete(f"/project/{project_id}")

    if response.get("error"):
        print(f"Error deleting project {project_id}: {response['error']}")
        return False

    return True
