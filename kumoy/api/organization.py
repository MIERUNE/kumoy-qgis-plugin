from dataclasses import dataclass
from typing import List, Literal, Optional

from .client import ApiClient


@dataclass
class Organization:
    id: str
    name: str
    stripeCustomerId: Optional[str]
    subscriptionPlan: str
    storageUnits: int
    createdAt: str
    updatedAt: str


@dataclass
class OrganizationWithRole(Organization):
    role: Literal["OWNER", "ADMIN", "MEMBER"]


def get_organizations() -> List[OrganizationWithRole]:
    """
    Get a list of organizations

    Returns:
        List of Organization objects
    """
    response = ApiClient.get("/organization")

    organizations = []
    for org in response:
        organizations.append(
            OrganizationWithRole(
                id=org.get("id", ""),
                name=org.get("name", ""),
                subscriptionPlan=org.get("subscriptionPlan", ""),
                stripeCustomerId=org.get("stripeCustomerId", ""),
                createdAt=org.get("createdAt", ""),
                updatedAt=org.get("updatedAt", ""),
                storageUnits=org.get("storageUnits", 0),
                role=org.get("role", "MEMBER"),
            )
        )
    return organizations


@dataclass
class OrganizationUsage:
    projects: int
    vectors: int
    styledMaps: int
    organizationMembers: int
    usedStorageUnits: float


@dataclass
class OrganizationDetail(OrganizationWithRole):
    usage: OrganizationUsage
    availableStorageUnits: int


def get_organization(organization_id: str) -> OrganizationDetail:
    """
    Get details for a specific organization

    Args:
        organization_id: Organization ID

    Returns:
        Organization object or None if not found
    """
    response = ApiClient.get(f"/organization/{organization_id}")

    return OrganizationDetail(
        id=response.get("id", ""),
        name=response.get("name", ""),
        subscriptionPlan=response.get("subscriptionPlan", ""),
        stripeCustomerId=response.get("stripeCustomerId", ""),
        storageUnits=response.get("storageUnits", 0),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
        role=response.get("role", "MEMBER"),
        usage=OrganizationUsage(
            projects=response.get("usage", {}).get("projects", 0),
            vectors=response.get("usage", {}).get("vectors", 0),
            styledMaps=response.get("usage", {}).get("styledMaps", 0),
            organizationMembers=response.get("usage", {}).get("organizationMembers", 0),
            usedStorageUnits=response.get("usage", {}).get("usedStorageUnits", 0),
        ),
        availableStorageUnits=response.get("availableStorageUnits", 0),
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
        subscriptionPlan=response.get("subscriptionPlan", ""),
        stripeCustomerId=response.get("stripeCustomerId", ""),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
        storageUnits=response.get("storageUnits", 0),
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
        subscriptionPlan=response.get("subscriptionPlan", ""),
        stripeCustomerId=response.get("stripeCustomerId", ""),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
        storageUnits=response.get("storageUnits", 0),
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
