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

    organizations = []
    for org in response:
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


def get_organization(organization_id: str) -> Organization:
    """
    Get details for a specific organization

    Args:
        organization_id: Organization ID

    Returns:
        Organization object or None if not found
    """
    response = ApiClient.get(f"/organization/{organization_id}")

    return Organization(
        id=response.get("id", ""),
        name=response.get("name", ""),
        plan=response.get("subscriptionPlan", ""),
        stripeCustomerId=response.get("stripeCustomerId", ""),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
    )


def create_organization(name: str) -> Organization:
    """
    Create a new organization

    Args:
        name: Organization name

    Returns:
        Organization object or None if creation failed
    """
    response = ApiClient.post("/organization", {"name": name})

    return Organization(
        id=response.get("id", ""),
        name=response.get("name", ""),
        plan=response.get("subscriptionPlan", ""),
        stripeCustomerId=response.get("stripeCustomerId", ""),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
    )


def update_organization(organization_id: str, name: str) -> Organization:
    """
    Update an existing organization

    Args:
        organization_id: Organization ID
        name: New organization name

    Returns:
        Updated Organization object or None if update failed
    """

    response = ApiClient.put(f"/organization/{organization_id}", {"name": name})

    return Organization(
        id=response.get("id", ""),
        name=response.get("name", ""),
        plan=response.get("subscriptionPlan", ""),
        stripeCustomerId=response.get("stripeCustomerId", ""),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
    )


def delete_organization(organization_id: str):
    """
    Delete an organization

    Args:
        organization_id: Organization ID

    Returns:
        True if successful, False otherwise
    """
    ApiClient.delete(f"/organization/{organization_id}")
