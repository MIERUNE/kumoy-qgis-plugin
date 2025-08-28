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
    response = ApiClient.get(f"/plan/{plan}")
    
    if response.get("error"):
        print(f"Error fetching plan limits for plan {plan}: {response['error']}")
        return None
    
    if not response["content"]:
        return None
    
    return PlanLimits(
        maxProjects=response["content"].get("maxProjects", 0),
        maxVectors=response["content"].get("maxVectors", 0),
        maxStyledMaps=response["content"].get("maxStyledMaps", 0),
        maxOrganizationMembers=response["content"].get("maxOrganizationMembers", 0),
        maxVectorFeatures=response["content"].get("maxVectorFeatures", 0),
        maxVectorAttributes=response["content"].get("maxVectorAttributes", 0),
    )
