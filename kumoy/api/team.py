from dataclasses import dataclass
from typing import Literal

from .client import ApiClient
from .organization import Organization


@dataclass
class Team:
    id: str
    name: str
    description: str
    createdAt: str
    updatedAt: str
    organization_id: str
    organization: Organization


@dataclass
class TeamDetail(Team):
    role: Literal["OWNER", "ADMIN", "MEMBER"]


def get_teams(organization_id: str) -> Team:
    """
    Get a list of teams in an organization

    Args:
        organization_id: ID of the organization

    Returns:
        List of Team objects
    """
    response = ApiClient.get(f"/organization/{organization_id}/teams")

    teams = []
    for team in response:
        teams.append(
            Team(
                id=team.get("id", ""),
                name=team.get("name", ""),
                description=team.get("description", ""),
                createdAt=team.get("createdAt", ""),
                updatedAt=team.get("updatedAt", ""),
                organization_id=organization_id,
                organization=Organization(
                    id=team.get("organization", {}).get("id", ""),
                    name=team.get("organization", {}).get("name", ""),
                    subscriptionPlan=team.get("organization", {}).get(
                        "subscriptionPlan", ""
                    ),
                    stripeCustomerId=team.get("organization", {}).get(
                        "stripeCustomerId", ""
                    ),
                    storageUnits=team.get("organization", {}).get("storageUnits", 0),
                    createdAt=team.get("organization", {}).get("createdAt", ""),
                    updatedAt=team.get("organization", {}).get("updatedAt", ""),
                ),
            )
        )

    return teams
