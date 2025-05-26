from dataclasses import dataclass
from typing import List, Optional

from .client import ApiClient


@dataclass
class Organization:
    id: str
    name: str
    createdAt: str = ""
    updatedAt: str = ""


def get_organizations() -> List[Organization]:
    """
    Get a list of organizations

    Returns:
        List of Organization objects
    """
    try:
        response = ApiClient.get("/organization")

        organizations = []
        for org in response:
            organizations.append(
                Organization(
                    id=org.get("id", ""),
                    name=org.get("name", ""),
                    createdAt=org.get("createdAt", ""),
                    updatedAt=org.get("updatedAt", ""),
                )
            )
        return organizations
    except Exception as e:
        print(f"Error fetching organizations: {str(e)}")
        return []


def get_organization(organization_id: str) -> Optional[Organization]:
    """
    Get details for a specific organization

    Args:
        organization_id: Organization ID

    Returns:
        Organization object or None if not found
    """
    try:
        response = ApiClient.get(f"/organization/{organization_id}")

        if not response:
            return None

        return Organization(
            id=response.get("id", ""),
            name=response.get("name", ""),
            createdAt=response.get("createdAt", ""),
            updatedAt=response.get("updatedAt", ""),
        )
    except Exception as e:
        print(f"Error fetching organization {organization_id}: {str(e)}")
        return None


def create_organization(name: str) -> Optional[Organization]:
    """
    Create a new organization

    Args:
        name: Organization name

    Returns:
        Organization object or None if creation failed
    """
    try:
        data = {"name": name}

        response = ApiClient.post("/organization", data)

        if not response:
            return None

        return Organization(
            id=response.get("id", ""),
            name=response.get("name", ""),
            createdAt=response.get("createdAt", ""),
            updatedAt=response.get("updatedAt", ""),
        )
    except Exception as e:
        print(f"Error creating organization: {str(e)}")
        return None


def update_organization(organization_id: str, name: str) -> Optional[Organization]:
    """
    Update an existing organization

    Args:
        organization_id: Organization ID
        name: New organization name

    Returns:
        Updated Organization object or None if update failed
    """
    try:
        data = {"name": name}

        response = ApiClient.patch(f"/organization/{organization_id}", data)

        if not response:
            return None

        return Organization(
            id=response.get("id", ""),
            name=response.get("name", ""),
            createdAt=response.get("createdAt", ""),
            updatedAt=response.get("updatedAt", ""),
        )
    except Exception as e:
        print(f"Error updating organization {organization_id}: {str(e)}")
        return None


def delete_organization(organization_id: str) -> bool:
    """
    Delete an organization

    Args:
        organization_id: Organization ID

    Returns:
        True if successful, False otherwise
    """
    try:
        ApiClient.delete(f"/organization/{organization_id}")
        return True
    except Exception as e:
        print(f"Error deleting organization {organization_id}: {str(e)}")
        return False
