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


PlanType = Literal["FREE", "OPERATOR", "TEAM", "CUSTOM"]


def get_plan_limits(plan: PlanType) -> Optional[PlanLimits]:
    """
    Get plan limits for a specific plan type

    Args:
        plan: Plan type (FREE, OPERATOR, TEAM, CUSTOM)

    Returns:
        PlanLimits object or None if not found
    """
    try:
        response = ApiClient.get(f"/plan/{plan}")

        if not response:
            return None

        return PlanLimits(
            maxProjects=response.get("maxProjects", 0),
            maxVectors=response.get("maxVectors", 0),
            maxStyledMaps=response.get("maxStyledMaps", 0),
            maxOrganizationMembers=response.get("maxOrganizationMembers", 0),
            maxVectorFeatures=response.get("maxVectorFeatures", 0),
            maxVectorAttributes=response.get("maxVectorAttributes", 0),
        )
    except Exception as e:
        print(f"Error fetching plan limits for plan {plan}: {str(e)}")
        return None
