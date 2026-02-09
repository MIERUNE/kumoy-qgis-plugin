from dataclasses import dataclass
from typing import Literal

from .client import ApiClient


@dataclass
class PlanLimits:
    maxProjects: int
    maxVectors: int
    maxStyledMaps: int
    maxOrganizationMembers: int
    maxVectorFeatures: int
    maxVectorAttributes: int


PlanType = Literal["FREE", "TEAM", "CUSTOM"]


def get_plan_limits(plan: PlanType) -> PlanLimits:
    """
    Get plan limits for a specific plan type

    Args:
        plan: Plan type (FREE, OPERATOR, TEAM, CUSTOM)

    Returns:
        PlanLimits object or None if not found
    """
    response = ApiClient.get(f"/plan/{plan}")

    return PlanLimits(
        maxProjects=response.get("maxProjects", 0),
        maxVectors=response.get("maxVectors", 0),
        maxStyledMaps=response.get("maxStyledMaps", 0),
        maxOrganizationMembers=response.get("maxOrganizationMembers", 0),
        maxVectorFeatures=response.get("maxVectorFeatures", 0),
        maxVectorAttributes=response.get("maxVectorAttributes", 0),
    )
