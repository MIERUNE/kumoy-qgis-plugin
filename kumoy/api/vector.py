from typing import List, Optional

from . import client
from ._util import UNSET, compact
from .models import GeometryType, Vector, VectorDetail, from_dict, list_of


def get_vectors(project_id: str) -> List[Vector]:
    return list_of(Vector, client.get(f"/project/{project_id}/vector"))


def get_vector(vector_id: str) -> VectorDetail:
    return from_dict(VectorDetail, client.get(f"/vector/{vector_id}"))


def create_vector(
    project_id: str, name: str, type: GeometryType, attribution: str = ""
) -> str:
    """Create an empty vector and return its ID."""
    data = client.post(
        f"/project/{project_id}/vector",
        {"name": name, "type": type, "attribution": attribution},
    )
    return data["id"]


def update_vector(
    vector_id: str, name: Optional[str] = UNSET, attribution: Optional[str] = UNSET
) -> Vector:
    data = client.put(
        f"/vector/{vector_id}", compact(name=name, attribution=attribution)
    )
    return from_dict(Vector, data)


def delete_vector(vector_id: str) -> None:
    client.delete(f"/vector/{vector_id}")
