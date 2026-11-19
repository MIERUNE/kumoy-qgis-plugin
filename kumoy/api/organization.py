from typing import List

from . import client
from .models import (
    OrganizationDetail,
    OrganizationWithRole,
    ProjectInOrganization,
    TeamWithRole,
    from_dict,
    list_of,
)


def get_organizations() -> List[OrganizationWithRole]:
    return list_of(OrganizationWithRole, client.get("/organization"))


def get_organization(organization_id: str) -> OrganizationDetail:
    return from_dict(OrganizationDetail, client.get(f"/organization/{organization_id}"))


def get_projects(organization_id: str) -> List[ProjectInOrganization]:
    """Projects of the user's teams in the organization, with item counts."""
    data = client.get(f"/organization/{organization_id}/projects")
    return list_of(ProjectInOrganization, data)


def get_my_teams(organization_id: str) -> List[TeamWithRole]:
    """The user's teams with their team role (which decides write access)."""
    return list_of(TeamWithRole, client.get(f"/organization/{organization_id}/myteams"))
