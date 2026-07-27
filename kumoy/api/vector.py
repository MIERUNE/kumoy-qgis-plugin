from dataclasses import dataclass
from typing import List, Literal, Optional

from .client import ApiClient
from .organization import Organization
from .project import Project
from .team import Team


@dataclass
class KumoyVector:
    id: str
    name: str
    type: Literal["POINT", "LINESTRING", "POLYGON"]
    # VectorはProjectかCatalogのどちらか一方に排他的に所有される。
    # Catalog所有時は projectId/project が None になり catalogId が入る。
    projectId: Optional[str]
    catalogId: Optional[str]
    project: Optional[Project]
    attribution: str
    storageUnits: float
    createdAt: str
    updatedAt: str


# extends KumoyVector
@dataclass
class KumoyVectorDetail(KumoyVector):
    role: Literal["ADMIN", "OWNER", "MEMBER"]
    extent: List[float]
    count: int
    columns: List[dict]


@dataclass
class KumoyVectorInProject:
    id: str
    name: str
    uri: str
    type: Literal["POINT", "LINESTRING", "POLYGON"]
    bytes: int
    createdAt: str
    updatedAt: str


def _parse_project(project_data: Optional[dict]) -> Optional[Project]:
    """レスポンスの ``project`` オブジェクトをパースする。Catalog所有時は None。"""
    if not project_data:
        return None

    team_data = project_data.get("team", {})
    organization_data = team_data.get("organization", {})
    return Project(
        id=project_data.get("id", ""),
        name=project_data.get("name", ""),
        description=project_data.get("description", ""),
        createdAt=project_data.get("createdAt", ""),
        updatedAt=project_data.get("updatedAt", ""),
        teamId=team_data.get("id", ""),
        team=Team(
            id=team_data.get("id", ""),
            name=team_data.get("name", ""),
            createdAt=team_data.get("createdAt", ""),
            updatedAt=team_data.get("updatedAt", ""),
            organizationId=team_data.get("organizationId", ""),
            organization=Organization(
                id=organization_data.get("id", ""),
                name=organization_data.get("name", ""),
                subscriptionPlan=organization_data.get("subscriptionPlan", ""),
                stripeCustomerId=organization_data.get("stripeCustomerId", ""),
                storageUnits=organization_data.get("storageUnits", 0),
                createdAt=organization_data.get("createdAt", ""),
                updatedAt=organization_data.get("updatedAt", ""),
            ),
        ),
    )


def get_vectors(project_id: str) -> List[KumoyVector]:
    """
    Get a list of vectors for a specific project

    Args:
        project_id: Project ID

    Returns:
        List of KumoyVector objects
    """
    response = ApiClient.get(f"/project/{project_id}/vector")
    vectors: List[KumoyVector] = []
    for vector_data in response:
        vectors.append(
            KumoyVector(
                id=vector_data.get("id", ""),
                name=vector_data.get("name", ""),
                type=vector_data.get("type", "POINT"),
                projectId=vector_data.get("projectId"),
                catalogId=vector_data.get("catalogId"),
                project=_parse_project(vector_data.get("project")),
                attribution=vector_data.get("attribution", ""),
                storageUnits=vector_data.get("storageUnits", 0),
                createdAt=vector_data.get("createdAt", ""),
                updatedAt=vector_data.get("updatedAt", ""),
            )
        )
    return vectors


def get_vector(vector_id: str) -> KumoyVectorDetail:
    """
    Get details for a specific vector
    """
    response = ApiClient.get(f"/vector/{vector_id}")

    vector = KumoyVectorDetail(
        id=response.get("id", ""),
        name=response.get("name", ""),
        type=response.get("type", "POINT"),
        projectId=response.get("projectId"),
        catalogId=response.get("catalogId"),
        project=_parse_project(response.get("project")),
        attribution=response.get("attribution", ""),
        storageUnits=response.get("storageUnits", 0),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
        extent=response.get("extent", []),
        count=response.get("count", 0),
        columns=response.get("columns", []),
        role=response.get("role", "MEMBER"),
    )

    return vector


@dataclass
class AddVectorOptions:
    name: str
    type: Literal["POINT", "LINESTRING", "POLYGON"]
    attribution: Optional[str] = None


@dataclass
class AddVectorResponse:
    id: str
    name: str
    uri: str
    type: Literal["POINT", "LINESTRING", "POLYGON"]
    projectId: Optional[str]
    catalogId: Optional[str]
    attribution: str
    bytes: int
    createdAt: str
    updatedAt: str


def add_vector(
    project_id: str, add_vector_options: AddVectorOptions
) -> AddVectorResponse:
    """
    Add a new vector to a project

    Args:
        project_id: Project ID
        add_vector_options: Options for the new vector

    Returns:
        KumoyVector object or None if creation failed
    """
    return _add_vector(f"/project/{project_id}/vector", add_vector_options)


def add_vector_to_catalog(
    catalog_id: str, add_vector_options: AddVectorOptions
) -> AddVectorResponse:
    """Catalogへ直接Vectorを作成する（組織ADMIN/OWNERのみ）。"""
    return _add_vector(f"/catalog/{catalog_id}/vector", add_vector_options)


def _add_vector(
    endpoint: str, add_vector_options: AddVectorOptions
) -> AddVectorResponse:
    payload = {
        "name": add_vector_options.name,
        "type": add_vector_options.type,
    }
    if add_vector_options.attribution is not None:
        payload["attribution"] = add_vector_options.attribution

    response = ApiClient.post(endpoint, payload)

    return AddVectorResponse(
        id=response.get("id", ""),
        name=response.get("name", ""),
        uri=response.get("uri", ""),
        type=response.get("type", "POINT"),
        projectId=response.get("projectId"),
        catalogId=response.get("catalogId"),
        attribution=response.get("attribution", ""),
        bytes=response.get("bytes", 0),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
    )


def delete_vector(vector_id: str) -> None:
    """
    Delete a vector from a project

    Args:
        project_id: Project ID
        vector_id: Vector ID

    Returns:
        True if successful, False otherwise
    """
    ApiClient.delete(f"/vector/{vector_id}")


@dataclass
class UpdateVectorOptions:
    name: Optional[str] = None
    attribution: Optional[str] = None


@dataclass
class UpdateVectorResponse:
    id: str
    name: str
    uri: str
    type: Literal["POINT", "LINESTRING", "POLYGON"]
    projectId: Optional[str]
    catalogId: Optional[str]
    attribution: str
    bytes: int
    createdAt: str
    updatedAt: str


def update_vector(
    vector_id: str, update_vector_options: UpdateVectorOptions
) -> UpdateVectorResponse:
    """
    Update an existing vector

    Args:
        vector_id: Vector ID
        update_vector_options: Update options

    Returns:
        KumoyVector object
    """

    payload = {}
    if update_vector_options.name is not None:
        payload["name"] = update_vector_options.name
    if update_vector_options.attribution is not None:
        payload["attribution"] = update_vector_options.attribution

    response = ApiClient.put(f"/vector/{vector_id}", payload)

    return UpdateVectorResponse(
        id=response.get("id", ""),
        name=response.get("name", ""),
        uri=response.get("uri", ""),
        type=response.get("type", "POINT"),
        projectId=response.get("projectId"),
        catalogId=response.get("catalogId"),
        attribution=response.get("attribution", ""),
        bytes=response.get("bytes", 0),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
    )
