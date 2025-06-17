from dataclasses import dataclass
from typing import List, Optional

from .client import ApiClient


@dataclass
class Project:
    id: str
    name: str
    organizationId: str = ""
    organizationName: str = ""
    planName: str = ""
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
    try:
        response = ApiClient.get(f"/organization/{organization_id}/projects")

        projects = []
        for project in response:
            projects.append(
                Project(
                    id=project.get("id", ""),
                    name=project.get("name", ""),
                    organizationId=organization_id,
                    organizationName="",  # Not available in list response
                    planName="",  # Not available in list response
                    createdAt=project.get("createdAt", ""),
                    updatedAt=project.get("updatedAt", ""),
                )
            )

        return projects
    except Exception as e:
        print(f"Error fetching projects for organization {organization_id}: {str(e)}")
        return []


def get_project(project_id: str) -> Optional[Project]:
    """
    Get details for a specific project

    Args:
        project_id: Project ID

    Returns:
        Project object or None if not found
    """
    try:
        response = ApiClient.get(f"/project/{project_id}")

        if not response:
            return None

        # Extract organization information from nested organization object
        organization = response.get("organization", {})
        organization_id = organization.get("id", "") if organization else ""
        organization_name = organization.get("name", "") if organization else ""
        # For now, use organization name as plan name (e.g., "free")
        # Convert to uppercase to match API plan enum
        plan_name = organization_name.upper() if organization_name else ""

        return Project(
            id=response.get("id", ""),
            name=response.get("name", ""),
            organizationId=organization_id,
            organizationName=organization_name,
            planName=plan_name,
            createdAt=response.get("createdAt", ""),
            updatedAt=response.get("updatedAt", ""),
        )
    except Exception as e:
        print(f"Error fetching project {project_id}: {str(e)}")
        return None


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
    try:
        data = {
            "name": name,
            "description": description,
            "organizationId": organization_id,
        }

        response = ApiClient.post("/project", data)

        if not response:
            return None

        return Project(
            id=response.get("id", ""),
            name=response.get("name", ""),
            organizationId=response.get("organizationId", ""),
            organizationName="",  # Not available in create response
            planName="",  # Not available in create response
            createdAt=response.get("createdAt", ""),
            updatedAt=response.get("updatedAt", ""),
        )
    except Exception as e:
        print(f"Error creating project: {str(e)}")
        return None


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
    try:
        data = {
            "name": name,
            "description": description,
        }

        response = ApiClient.patch(f"/project/{project_id}", data)

        if not response:
            return None

        return Project(
            id=response.get("id", ""),
            name=response.get("name", ""),
            organizationId=response.get("organizationId", ""),
            organizationName="",  # Not available in create response
            planName="",  # Not available in create response
            createdAt=response.get("createdAt", ""),
            updatedAt=response.get("updatedAt", ""),
        )
    except Exception as e:
        print(f"Error updating project {project_id}: {str(e)}")
        return None


def delete_project(project_id: str) -> bool:
    """
    Delete a project

    Args:
        project_id: Project ID

    Returns:
        True if successful, False otherwise
    """
    try:
        ApiClient.delete(f"/project/{project_id}")
        return True
    except Exception as e:
        print(f"Error deleting project {project_id}: {str(e)}")
        return False
