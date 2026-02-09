from dataclasses import dataclass
from typing import Literal, Optional

from .client import ApiClient


@dataclass
class PlanLimits:
    maxProjects: int
    maxVectors: int
    maxStyledMaps: int
    maxOrganizationMembers: int
    maxVectorFeatures: int
    maxVectorAttributes: int
    defaultStorageUnits: int


PlanType = Literal["FREE", "TEAM", "CUSTOM"]


def get_plan_limits(
    plan: PlanType, purchased_storage_units: Optional[int] = None
) -> PlanLimits:
    """
    Get plan limits for a specific plan type

    Args:
        plan: Plan type (FREE, TEAM, CUSTOM)
        purchased_storage_units: Number of purchased storage units

    Returns:
        PlanLimits object or None if not found
    """
    params = None
    if purchased_storage_units is not None:
        params = {"purchasedStorageUnits": str(purchased_storage_units)}

    response = ApiClient.get(f"/plan/{plan}", params=params)

    return PlanLimits(
        maxProjects=response.get("maxProjects", 0),
        maxVectors=response.get("maxVectors", 0),
        maxStyledMaps=response.get("maxStyledMaps", 0),
        maxOrganizationMembers=response.get("maxOrganizationMembers", 0),
        maxVectorFeatures=response.get("maxVectorFeatures", 0),
        maxVectorAttributes=response.get("maxVectorAttributes", 0),
        defaultStorageUnits=response.get("defaultStorageUnits", 0),
    )
