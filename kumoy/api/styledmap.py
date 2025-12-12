from dataclasses import dataclass
from typing import List, Literal, Optional, Union

from .client import ApiClient
from .organization import Organization
from .project import Project
from .team import Team


@dataclass
class KumoyStyledMap:
    """
    KUMOYのStyledMapを表すデータクラス
    """

    id: str
    name: str
    description: str
    isPublic: bool
    projectId: str
    project: Project
    attribution: str
    thumbnailImageUrl: str
    createdAt: str
    updatedAt: str


def get_styled_maps(project_id: str) -> List[KumoyStyledMap]:
    """
    特定のプロジェクトのスタイルマップリストを取得する

    Args:
        project_id: プロジェクトID

    Returns:
        KumoyStyledMapオブジェクトのリスト
    """
    response = ApiClient.get(f"/project/{project_id}/styled-map")

    styled_maps = []
    for styled_map_data in response:
        styled_maps.append(
            KumoyStyledMap(
                id=styled_map_data.get("id", ""),
                name=styled_map_data.get("name", ""),
                isPublic=styled_map_data.get("isPublic", False),
                projectId=project_id,
                project=Project(
                    id=styled_map_data.get("project", {}).get("id", ""),
                    name=styled_map_data.get("project", {}).get("name", ""),
                    description=styled_map_data.get("project", {}).get(
                        "description", ""
                    ),
                    createdAt=styled_map_data.get("project", {}).get("createdAt", ""),
                    updatedAt=styled_map_data.get("project", {}).get("updatedAt", ""),
                    teamId=styled_map_data.get("project", {})
                    .get("team", {})
                    .get("id", ""),
                    team=Team(
                        id=styled_map_data.get("project", {})
                        .get("team", {})
                        .get("id", ""),
                        name=styled_map_data.get("project", {})
                        .get("team", {})
                        .get("name", ""),
                        description=styled_map_data.get("project", {})
                        .get("team", {})
                        .get("description", ""),
                        createdAt=styled_map_data.get("project", {})
                        .get("team", {})
                        .get("createdAt", ""),
                        updatedAt=styled_map_data.get("project", {})
                        .get("team", {})
                        .get("updatedAt", ""),
                        organization_id=styled_map_data.get("project", {})
                        .get("team", {})
                        .get("organization", {})
                        .get("id", ""),
                        organization=Organization(
                            id=styled_map_data.get("project", {})
                            .get("team", {})
                            .get("organization", {})
                            .get("id", ""),
                            name=styled_map_data.get("project", {})
                            .get("team", {})
                            .get("organization", {})
                            .get("name", ""),
                            subscriptionPlan=styled_map_data.get("project", {})
                            .get("team", {})
                            .get("organization", {})
                            .get("subscriptionPlan", ""),
                            stripeCustomerId=styled_map_data.get("project", {})
                            .get("team", {})
                            .get("organization", {})
                            .get("stripeCustomerId", ""),
                            storageUnits=styled_map_data.get("project", {})
                            .get("team", {})
                            .get("organization", {})
                            .get("storageUnits", 0),
                            createdAt=styled_map_data.get("project", {})
                            .get("team", {})
                            .get("organization", {})
                            .get("createdAt", ""),
                            updatedAt=styled_map_data.get("project", {})
                            .get("team", {})
                            .get("organization", {})
                            .get("updatedAt", ""),
                        ),
                    ),
                ),
                description=styled_map_data.get("description", ""),
                attribution=styled_map_data.get("attribution", ""),
                thumbnailImageUrl=styled_map_data.get("thumbnailImageUrl"),
                createdAt=styled_map_data.get("createdAt", ""),
                updatedAt=styled_map_data.get("updatedAt", ""),
            )
        )

    return styled_maps


@dataclass
class KumoyStyledMapDetail(KumoyStyledMap):
    """
    KUMOYのStyledMapの詳細を表すデータクラス
    """

    qgisproject: str
    role: Literal["ADMIN", "OWNER", "MEMBER"]


def get_styled_map(styled_map_id: str) -> KumoyStyledMapDetail:
    """
    特定のスタイルマップの詳細を取得する

    Args:
        styled_map_id: スタイルマップID

    Returns:
        KumoyStyledMapオブジェクトまたは見つからない場合はNone
    """
    response = ApiClient.post(f"/_qgis/styled-map/{styled_map_id}", {})

    return KumoyStyledMapDetail(
        id=response.get("id", ""),
        name=response.get("name", ""),
        isPublic=response.get("isPublic", False),
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
        description=response.get("description", ""),
        attribution=response.get("attribution", ""),
        thumbnailImageUrl=response.get("thumbnailImageUrl"),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
        qgisproject=response.get("qgisproject", ""),
        role=response.get("role", "MEMBER"),
    )


@dataclass
class AddStyledMapOptions:
    """
    新しいスタイルマップを追加するためのオプション
    """

    name: str
    qgisproject: str


def add_styled_map(
    project_id: str, options: AddStyledMapOptions
) -> KumoyStyledMapDetail:
    """
    プロジェクトに新しいスタイルマップを追加する

    Args:
        project_id: プロジェクトID
        options: 新しいスタイルマップのオプション

    Returns:
        KumoyStyledMapオブジェクトまたは作成失敗時はNone
    """
    response = ApiClient.post(
        f"/project/{project_id}/styled-map",
        {
            "name": options.name,
            "qgisproject": options.qgisproject,
        },
    )

    return KumoyStyledMap(
        id=response.get("id", ""),
        name=response.get("name", ""),
        isPublic=response.get("isPublic", False),
        projectId=project_id,
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
        description=response.get("description", ""),
        attribution=response.get("attribution", ""),
        thumbnailImageUrl=response.get("thumbnailImageUrl"),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
    )


def delete_styled_map(styled_map_id: str) -> bool:
    """
    スタイルマップを削除する

    Args:
        styled_map_id: スタイルマップID

    Returns:
        成功した場合はTrue、それ以外はFalse
    """
    ApiClient.delete(f"/styled-map/{styled_map_id}")


@dataclass
class UpdateStyledMapOptions:
    """
    スタイルマップを更新するためのオプション
    """

    name: Optional[str] = None
    qgisproject: Optional[str] = None
    isPublic: Optional[bool] = None


def update_styled_map(
    styled_map_id: str, options: UpdateStyledMapOptions
) -> KumoyStyledMapDetail:
    """
    スタイルマップを更新する

    Args:
        styled_map_id: スタイルマップID
        options: 更新オプション

    Returns:
        更新されたKumoyStyledMapオブジェクトまたは更新失敗時はNone
    """
    update_data = {}
    if options.name is not None:
        update_data["name"] = options.name
    if options.qgisproject is not None:
        update_data["qgisproject"] = options.qgisproject
    if options.isPublic is not None:
        update_data["isPublic"] = options.isPublic

    response = ApiClient.put(
        f"/styled-map/{styled_map_id}",
        update_data,
    )

    return KumoyStyledMap(
        id=response.get("id", ""),
        name=response.get("name", ""),
        isPublic=response.get("isPublic", False),
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
        description=response.get("description", ""),
        attribution=response.get("attribution", ""),
        thumbnailImageUrl=response.get("thumbnailImageUrl"),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
    )
