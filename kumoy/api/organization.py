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
    # Set when the organization is deactivated and awaiting deletion (ISO 8601).
    # Such organizations are unusable: detail/project APIs return not found.
    scheduledDeletionAt: Optional[str]


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
                scheduledDeletionAt=org.get("scheduledDeletionAt"),
            )
        )
    return organizations


@dataclass
class OrganizationUsage:
    projects: int
    vectors: int
    rasters: int
    styledMaps: int
    # Seats are counted against the plan including pending invites: add
    # organizationInvites to organizationMembers, while organizationEditors
    # already includes organizationEditorInvites.
    organizationMembers: int
    organizationInvites: int
    organizationEditors: int
    organizationEditorInvites: int
    usedStorageUnits: float


@dataclass
class PlanSettings:
    """Quotas of the organization's plan, with CUSTOM plan overrides applied."""

    maxProjects: int
    maxVectors: int
    maxRasters: int
    maxStyledMaps: int
    maxTeams: int
    maxOrganizationMembers: int
    maxEditors: int
    maxVectorFeatures: int
    maxVectorAttributes: int
    defaultStorageUnits: int
    activityLogViewableDays: int
    canUseKeyphrase: bool
    canEditFeaturesOnWeb: bool


@dataclass
class OrganizationDetail(OrganizationWithRole):
    usage: OrganizationUsage
    availableStorageUnits: int
    planSettings: PlanSettings


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
        scheduledDeletionAt=response.get("scheduledDeletionAt"),
        usage=OrganizationUsage(
            projects=response.get("usage", {}).get("projects", 0),
            vectors=response.get("usage", {}).get("vectors", 0),
            rasters=response.get("usage", {}).get("rasters", 0),
            styledMaps=response.get("usage", {}).get("styledMaps", 0),
            organizationMembers=response.get("usage", {}).get("organizationMembers", 0),
            organizationInvites=response.get("usage", {}).get("organizationInvites", 0),
            organizationEditors=response.get("usage", {}).get("organizationEditors", 0),
            organizationEditorInvites=response.get("usage", {}).get(
                "organizationEditorInvites", 0
            ),
            usedStorageUnits=response.get("usage", {}).get("usedStorageUnits", 0),
        ),
        availableStorageUnits=response.get("availableStorageUnits", 0),
        planSettings=_parse_plan_settings(response.get("planSettings", {})),
    )


def _parse_plan_settings(settings: dict) -> PlanSettings:
    return PlanSettings(
        maxProjects=settings.get("maxProjects", 0),
        maxVectors=settings.get("maxVectors", 0),
        maxRasters=settings.get("maxRasters", 0),
        maxStyledMaps=settings.get("maxStyledMaps", 0),
        maxTeams=settings.get("maxTeams", 0),
        maxOrganizationMembers=settings.get("maxOrganizationMembers", 0),
        maxEditors=settings.get("maxEditors", 0),
        maxVectorFeatures=settings.get("maxVectorFeatures", 0),
        maxVectorAttributes=settings.get("maxVectorAttributes", 0),
        defaultStorageUnits=settings.get("defaultStorageUnits", 0),
        activityLogViewableDays=settings.get("activityLogViewableDays", 0),
        canUseKeyphrase=settings.get("canUseKeyphrase", False),
        canEditFeaturesOnWeb=settings.get("canEditFeaturesOnWeb", False),
    )
