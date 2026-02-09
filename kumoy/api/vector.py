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
    projectId: str
    project: Project
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
                projectId=vector_data.get("projectId", ""),
                project=Project(
                    id=vector_data.get("project", {}).get("id", ""),
                    name=vector_data.get("project", {}).get("name", ""),
                    description=vector_data.get("project", {}).get("description", ""),
                    createdAt=vector_data.get("project", {}).get("createdAt", ""),
                    updatedAt=vector_data.get("project", {}).get("updatedAt", ""),
                    teamId=vector_data.get("project", {}).get("team", {}).get("id", ""),
                    team=Team(
                        id=vector_data.get("project", {}).get("team", {}).get("id", ""),
                        name=vector_data.get("project", {})
                        .get("team", {})
                        .get("name", ""),
                        createdAt=vector_data.get("project", {})
                        .get("team", {})
                        .get("createdAt", ""),
                        updatedAt=vector_data.get("project", {})
                        .get("team", {})
                        .get("updatedAt", ""),
                        organizationId=vector_data.get("project", {})
                        .get("team", {})
                        .get("organizationId", ""),
                        organization=Organization(
                            id=vector_data.get("project", {})
                            .get("team", {})
                            .get("organization", {})
                            .get("id", ""),
                            name=vector_data.get("project", {})
                            .get("team", {})
                            .get("organization", {})
                            .get("name", ""),
                            subscriptionPlan=vector_data.get("project", {})
                            .get("team", {})
                            .get("organization", {})
                            .get("subscriptionPlan", ""),
                            stripeCustomerId=vector_data.get("project", {})
                            .get("team", {})
                            .get("organization", {})
                            .get("stripeCustomerId", ""),
                            storageUnits=vector_data.get("project", {})
                            .get("team", {})
                            .get("organization", {})
                            .get("storageUnits", 0),
                            createdAt=vector_data.get("project", {})
                            .get("team", {})
                            .get("organization", {})
                            .get("createdAt", ""),
                            updatedAt=vector_data.get("project", {})
                            .get("team", {})
                            .get("organization", {})
                            .get("updatedAt", ""),
                        ),
                    ),
                ),
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
        projectId=response.get("projectId", ""),
        project=Project(
            id=response.get("project", {}).get("id", ""),
            name=response.get("project", {}).get("name", ""),
            description=response.get("project", {}).get("description", ""),
            createdAt=response.get("project", {}).get("createdAt", ""),
            updatedAt=response.get("project", {}).get("updatedAt", ""),
            teamId=response.get("project", {}).get("team", {}).get("id", ""),
            team=Team(
                id=response.get("project", {}).get("team", {}).get("id", ""),
                name=response.get("project", {}).get("team", {}).get("name", ""),
                createdAt=response.get("project", {})
                .get("team", {})
                .get("createdAt", ""),
                updatedAt=response.get("project", {})
                .get("team", {})
                .get("updatedAt", ""),
                organizationId=response.get("project", {})
                .get("team", {})
                .get("organizationId", ""),
                organization=Organization(
                    id=response.get("project", {})
                    .get("team", {})
                    .get("organization", {})
                    .get("id", ""),
                    name=response.get("project", {})
                    .get("team", {})
                    .get("organization", {})
                    .get("name", ""),
                    subscriptionPlan=response.get("project", {})
                    .get("team", {})
                    .get("organization", {})
                    .get("subscriptionPlan", ""),
                    stripeCustomerId=response.get("project", {})
                    .get("team", {})
                    .get("organization", {})
                    .get("stripeCustomerId", ""),
                    storageUnits=response.get("project", {})
                    .get("team", {})
                    .get("organization", {})
                    .get("storageUnits", 0),
                    createdAt=response.get("project", {})
                    .get("team", {})
                    .get("organization", {})
                    .get("createdAt", ""),
                    updatedAt=response.get("project", {})
                    .get("team", {})
                    .get("organization", {})
                    .get("updatedAt", ""),
                ),
            ),
        ),
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
    projectId: str
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

    payload = {
        "name": add_vector_options.name,
        "type": add_vector_options.type,
    }
    if add_vector_options.attribution is not None:
        payload["attribution"] = add_vector_options.attribution

    response = ApiClient.post(f"/project/{project_id}/vector", payload)

    return AddVectorResponse(
        id=response.get("id", ""),
        name=response.get("name", ""),
        uri=response.get("uri", ""),
        type=response.get("type", "POINT"),
        projectId=response.get("projectId", ""),
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
    projectId: str
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
        projectId=response.get("projectId", ""),
        attribution=response.get("attribution", ""),
        bytes=response.get("bytes", 0),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
    )
