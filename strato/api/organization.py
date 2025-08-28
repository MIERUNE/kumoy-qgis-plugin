from dataclasses import dataclass
from typing import List, Optional

from .client import ApiClient


@dataclass
class Organization:
    id: str
    name: str
    plan: str = ""
    stripeCustomerId: str = ""
    createdAt: str = ""
    updatedAt: str = ""


def get_organizations() -> List[Organization]:
    """
    Get a list of organizations

    Returns:
        List of Organization objects
    """
    response = ApiClient.get("/organization")
    
    if response.get("error"):
        print(f"Error fetching organizations: {response['error']}")
        return []
    
    organizations = []
    for org in response["content"]:
        organizations.append(
            Organization(
                id=org.get("id", ""),
                name=org.get("name", ""),
                plan=org.get("subscriptionPlan", ""),
                stripeCustomerId=org.get("stripeCustomerId", ""),
                createdAt=org.get("createdAt", ""),
                updatedAt=org.get("updatedAt", ""),
            )
        )
    return organizations


def get_organization(organization_id: str) -> Optional[Organization]:
    """
    Get details for a specific organization

    Args:
        organization_id: Organization ID

    Returns:
        Organization object or None if not found
    """
    response = ApiClient.get(f"/organization/{organization_id}")
    
    if response.get("error"):
        print(f"Error fetching organization {organization_id}: {response['error']}")
        return None
    
    if not response["content"]:
        return None
    
    return Organization(
        id=response["content"].get("id", ""),
        name=response["content"].get("name", ""),
        plan=response["content"].get("subscriptionPlan", ""),
        stripeCustomerId=response["content"].get("stripeCustomerId", ""),
        createdAt=response["content"].get("createdAt", ""),
        updatedAt=response["content"].get("updatedAt", ""),
    )


def create_organization(name: str) -> Optional[Organization]:
    """
    Create a new organization

    Args:
        name: Organization name

    Returns:
        Organization object or None if creation failed
    """
    data = {"name": name}
    
    response = ApiClient.post("/organization", data)
    
    if response.get("error"):
        print(f"Error creating organization: {response['error']}")
        return None
    
    if not response["content"]:
        return None
    
    return Organization(
        id=response["content"].get("id", ""),
        name=response["content"].get("name", ""),
        plan=response["content"].get("subscriptionPlan", ""),
        stripeCustomerId=response["content"].get("stripeCustomerId", ""),
        createdAt=response["content"].get("createdAt", ""),
        updatedAt=response["content"].get("updatedAt", ""),
    )


def update_organization(organization_id: str, name: str) -> Optional[Organization]:
    """
    Update an existing organization

    Args:
        organization_id: Organization ID
        name: New organization name

    Returns:
        Updated Organization object or None if update failed
    """
    data = {"name": name}
    
    response = ApiClient.patch(f"/organization/{organization_id}", data)
    
    if response.get("error"):
        print(f"Error updating organization {organization_id}: {response['error']}")
        return None
    
    if not response["content"]:
        return None
    
    return Organization(
        id=response["content"].get("id", ""),
        name=response["content"].get("name", ""),
        plan=response["content"].get("subscriptionPlan", ""),
        stripeCustomerId=response["content"].get("stripeCustomerId", ""),
        createdAt=response["content"].get("createdAt", ""),
        updatedAt=response["content"].get("updatedAt", ""),
    )


def delete_organization(organization_id: str) -> bool:
    """
    Delete an organization

    Args:
        organization_id: Organization ID

    Returns:
        True if successful, False otherwise
    """
    response = ApiClient.delete(f"/organization/{organization_id}")
    
    if response.get("error"):
        print(f"Error deleting organization {organization_id}: {response['error']}")
        return False
    
    return True
