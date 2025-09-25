from dataclasses import dataclass
from typing import Dict, List, Optional

from .client import ApiClient


@dataclass
class StratoStyledMap:
    """
    STRATOのStyledMapを表すデータクラス
    """

    id: str
    name: str
    isPublic: bool
    projectId: str


def get_styled_maps(project_id: str) -> List[StratoStyledMap]:
    """
    特定のプロジェクトのスタイルマップリストを取得する

    Args:
        project_id: プロジェクトID

    Returns:
        StratoStyledMapオブジェクトのリスト
    """
    response = ApiClient.get(f"/project/{project_id}/styled-map")
    styled_maps = []
    for styled_map_data in response:
        styled_maps.append(
            StratoStyledMap(
                id=styled_map_data.get("id", ""),
                name=styled_map_data.get("name", ""),
                isPublic=styled_map_data.get("isPublic", False),
                projectId=project_id,
            )
        )

    return styled_maps


@dataclass
class StratoStyledMapDetail(StratoStyledMap):
    """
    STRATOのStyledMapの詳細を表すデータクラス
    """

    qgisproject: str


def get_styled_map(styled_map_id: str) -> StratoStyledMapDetail:
    """
    特定のスタイルマップの詳細を取得する

    Args:
        styled_map_id: スタイルマップID

    Returns:
        StratoStyledMapオブジェクトまたは見つからない場合はNone
    """
    response = ApiClient.post(f"/_qgis/styled-map/{styled_map_id}", {})

    return StratoStyledMapDetail(
        id=response.get("id", ""),
        name=response.get("name", ""),
        qgisproject=response.get("qgisproject", ""),
        isPublic=response.get("isPublic", False),
        projectId=response.get("projectId", ""),
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
) -> StratoStyledMapDetail:
    """
    プロジェクトに新しいスタイルマップを追加する

    Args:
        project_id: プロジェクトID
        options: 新しいスタイルマップのオプション

    Returns:
        StratoStyledMapオブジェクトまたは作成失敗時はNone
    """
    response = ApiClient.post(
        f"/project/{project_id}/styled-map",
        {
            "name": options.name,
            "qgisproject": options.qgisproject,
        },
    )

    return StratoStyledMap(
        id=response.get("id", ""),
        name=response.get("name", ""),
        qgisproject=response.get("qgisproject", ""),
        isPublic=response.get("isPublic", False),
        projectId=project_id,
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
) -> StratoStyledMap:
    """
    スタイルマップを更新する

    Args:
        styled_map_id: スタイルマップID
        options: 更新オプション

    Returns:
        更新されたStratoStyledMapオブジェクトまたは更新失敗時はNone
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

    return StratoStyledMapDetail(
        id=response.get("id", ""),
        name=response.get("name", ""),
        qgisproject=response.get("qgisproject", ""),
        isPublic=response.get("isPublic", False),
        projectId=response.get("projectId", ""),
    )
