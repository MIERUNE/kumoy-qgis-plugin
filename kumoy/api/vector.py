from dataclasses import dataclass
from typing import Dict, List, Literal

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
    uri: str
    storageUnits: float
    createdAt: str
    updatedAt: str


# extends KumoyVector
@dataclass
class KumoyVectorDetail(KumoyVector):
    role: Literal["ADMIN", "OWNER", "MEMBER"]
    extent: List[float]
    count: int
    columns: Dict[str, str]


def get_vectors(project_id: str) -> List[KumoyVector]:
    """
    Get a list of vectors for a specific project

    Args:
        project_id: Project ID

    Returns:
        List of KumoyVector objects
    """
    response = ApiClient.get(f"/project/{project_id}/vector")
    vectors = []
    for vector_data in response:
        vectors.append(
            KumoyVector(
                id=vector_data.get("id", ""),
                name=vector_data.get("name", ""),
                uri=vector_data.get("uri", ""),
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
                        description=vector_data.get("project", {})
                        .get("team", {})
                        .get("description", ""),
                        createdAt=vector_data.get("project", {})
                        .get("team", {})
                        .get("createdAt", ""),
                        updatedAt=vector_data.get("project", {})
                        .get("team", {})
                        .get("updatedAt", ""),
                        organization_id=vector_data.get("project", {})
                        .get("team", {})
                        .get("organization", {})
                        .get("id", ""),
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


def get_vector(project_id: str, vector_id: str):
    """
    Get details for a specific vector
    """
    response = ApiClient.get(f"/vector/{vector_id}")

    vector = KumoyVectorDetail(
        id=response.get("id", ""),
        name=response.get("name", ""),
        uri=response.get("uri", ""),
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
                description=response.get("project", {})
                .get("team", {})
                .get("description", ""),
                createdAt=response.get("project", {})
                .get("team", {})
                .get("createdAt", ""),
                updatedAt=response.get("project", {})
                .get("team", {})
                .get("updatedAt", ""),
                organization_id=response.get("project", {})
                .get("team", {})
                .get("organization", {})
                .get("id", ""),
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
        columns=response.get("columns", {}),
        role=response.get("role", "MEMBER"),
    )

    return vector


@dataclass
class AddVectorOptions:
    name: str
    type: Literal["POINT", "LINESTRING", "POLYGON"]


def add_vector(project_id: str, add_vector_options: AddVectorOptions) -> KumoyVector:
    """
    Add a new vector to a project

    Args:
        project_id: Project ID
        add_vector_options: Options for the new vector

    Returns:
        KumoyVector object or None if creation failed
    """
    response = ApiClient.post(
        f"/project/{project_id}/vector",
        {"name": add_vector_options.name, "type": add_vector_options.type},
    )

    return KumoyVector(
        id=response.get("id", ""),
        name=response.get("name", ""),
        uri=response.get("uri", ""),
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
                description=response.get("project", {})
                .get("team", {})
                .get("description", ""),
                createdAt=response.get("project", {})
                .get("team", {})
                .get("createdAt", ""),
                updatedAt=response.get("project", {})
                .get("team", {})
                .get("updatedAt", ""),
                organization_id=response.get("project", {})
                .get("team", {})
                .get("organization", {})
                .get("id", ""),
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
    )


def delete_vector(vector_id: str):
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
    name: str


def update_vector(
    project_id: str, vector_id: str, update_vector_options: UpdateVectorOptions
) -> KumoyVector:
    """
    Update an existing vector

    Args:
        project_id: Project ID
        vector_id: Vector ID
        update_vector_options: Update options

    Returns:
        KumoyVector object or None if update failed
    """
    response = ApiClient.put(
        f"/vector/{vector_id}",
        {"name": update_vector_options.name},
    )
    return KumoyVector(
        id=response.get("id", ""),
        name=response.get("name", ""),
        uri=response.get("uri", ""),
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
                description=response.get("project", {})
                .get("team", {})
                .get("description", ""),
                createdAt=response.get("project", {})
                .get("team", {})
                .get("createdAt", ""),
                updatedAt=response.get("project", {})
                .get("team", {})
                .get("updatedAt", ""),
                organization_id=response.get("project", {})
                .get("team", {})
                .get("organization", {})
                .get("id", ""),
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
    )
