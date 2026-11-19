from typing import Optional

from . import client
from ._util import UNSET, compact
from .models import Project, ProjectDetail, from_dict


def get_project(project_id: str) -> ProjectDetail:
    return from_dict(ProjectDetail, client.get(f"/project/{project_id}"))


def create_project(team_id: str, name: str, description: str = "") -> Project:
    data = client.post(
        "/project", {"teamId": team_id, "name": name, "description": description}
    )
    return from_dict(Project, data)


def update_project(
    project_id: str, name: Optional[str] = UNSET, description: Optional[str] = UNSET
) -> Project:
    data = client.put(
        f"/project/{project_id}", compact(name=name, description=description)
    )
    return from_dict(Project, data)


def delete_project(project_id: str) -> None:
    client.delete(f"/project/{project_id}")
