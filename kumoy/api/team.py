from dataclasses import dataclass
from typing import List, Literal, Optional

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


@dataclass
class TeamMutationResult:
    id: str
    name: str
    organizationId: str
    createdAt: str
    updatedAt: str


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


def create_team(name: str, organization_id: str) -> TeamMutationResult:
    """
    Create a new team

    Args:
        name: Team name
        organization_id: Organization ID

    Returns:
        TeamMutationResult object
    """
    response = ApiClient.post(
        "/team", {"name": name, "organizationId": organization_id}
    )

    return TeamMutationResult(
        id=response.get("id", ""),
        name=response.get("name", ""),
        organizationId=response.get("organizationId", ""),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
    )


def update_team(team_id: str, name: Optional[str] = None) -> TeamMutationResult:
    """
    Update a team

    Args:
        team_id: Team ID
        name: New team name

    Returns:
        TeamMutationResult object
    """
    payload = {}
    if name is not None:
        payload["name"] = name

    response = ApiClient.put(f"/team/{team_id}", payload)

    return TeamMutationResult(
        id=response.get("id", ""),
        name=response.get("name", ""),
        organizationId=response.get("organizationId", ""),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
    )


def delete_team(team_id: str) -> None:
    """
    Delete a team

    Args:
        team_id: Team ID
    """
    ApiClient.delete(f"/team/{team_id}")
