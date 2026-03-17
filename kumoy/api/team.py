from dataclasses import dataclass
from typing import List, Literal

from .client import ApiClient
from .organization import Organization


@dataclass
class Team:
    id: str
    name: str
    createdAt: str
    updatedAt: str
    organizationId: str
    organization: Organization


@dataclass
class TeamDetail(Team):
    role: Literal["OWNER", "ADMIN", "MEMBER"]


def get_teams(organization_id: str) -> List[Team]:
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
                createdAt=team.get("createdAt", ""),
                updatedAt=team.get("updatedAt", ""),
                organizationId=organization_id,
                organization=Organization(
                    id=team.get("organization", {}).get("id", ""),
                    name=team.get("organization", {}).get("name", ""),
                    # MEMO: 以下のフィールドはAPIからはまだ返ってきていない
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


def get_team(team_id: str) -> TeamDetail:
    """
    Get a team by ID

    Args:
        team_id: Team ID

    Returns:
        TeamDetail object
    """
    response = ApiClient.get(f"/team/{team_id}")

    return TeamDetail(
        id=response.get("id", ""),
        name=response.get("name", ""),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
        organizationId=response.get("organization", {}).get("id", ""),
        organization=Organization(
            id=response.get("organization", {}).get("id", ""),
            name=response.get("organization", {}).get("name", ""),
            # MEMO: 以下のフィールドはAPIからはまだ返ってきていない
            subscriptionPlan=response.get("organization", {}).get(
                "subscriptionPlan", ""
            ),
            stripeCustomerId=response.get("organization", {}).get(
                "stripeCustomerId", ""
            ),
            storageUnits=response.get("organization", {}).get("storageUnits", 0),
            createdAt=response.get("organization", {}).get("createdAt", ""),
            updatedAt=response.get("organization", {}).get("updatedAt", ""),
        ),
        role=response.get("role", "MEMBER"),
    )


def get_organization_myteams(org_id: str) -> List[TeamDetail]:
    """
    Get teams that the authenticated user belongs to in an organization

    Args:
        org_id: Organization ID

    Returns:
        List of TeamDetail objects
    """
    response = ApiClient.get(f"/organization/{org_id}/myteams")

    teams = []
    for team in response:
        teams.append(
            TeamDetail(
                id=team.get("id", ""),
                name=team.get("name", ""),
                createdAt=team.get("createdAt", ""),
                updatedAt=team.get("updatedAt", ""),
                organizationId=org_id,
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
                role=team.get("role", "MEMBER"),
            )
        )

    return teams
