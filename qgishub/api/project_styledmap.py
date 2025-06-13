from dataclasses import dataclass
from typing import Dict, List, Optional

from .client import ApiClient


@dataclass
class QgishubStyledMap:
    """
    STRATOのStyledMapを表すデータクラス
    """

    id: str
    name: str
    qgisproject: str
    isPublic: bool
    projectId: str


def get_styled_maps(project_id: str) -> List[QgishubStyledMap]:
    """
    特定のプロジェクトのスタイルマップリストを取得する

    Args:
        project_id: プロジェクトID

    Returns:
        QgishubStyledMapオブジェクトのリスト
    """
    try:
        response = ApiClient.get(f"/project/{project_id}/styled-map")

        styled_maps = []
        for styled_map_data in response:
            styled_maps.append(
                QgishubStyledMap(
                    id=styled_map_data.get("id", ""),
                    name=styled_map_data.get("name", ""),
                    qgisproject=styled_map_data.get("qgisproject", ""),
                    isPublic=styled_map_data.get("isPublic", False),
                    projectId=project_id,
                )
            )

        return styled_maps
    except Exception as e:
        print(f"プロジェクト {project_id} のMap取得エラー: {str(e)}")
        return []


def get_styled_map(styled_map_id: str) -> Optional[QgishubStyledMap]:
    """
    特定のスタイルマップの詳細を取得する

    Args:
        styled_map_id: スタイルマップID

    Returns:
        QgishubStyledMapオブジェクトまたは見つからない場合はNone
    """
    try:
        response = ApiClient.get(f"/styled-map/{styled_map_id}")

        if not response:
            return None

        return QgishubStyledMap(
            id=response.get("id", ""),
            name=response.get("name", ""),
            qgisproject=response.get("qgisproject", ""),
            isPublic=response.get("isPublic", False),
            projectId=response.get("projectId", ""),
        )

    except Exception as e:
        print(f"スタイルマップ {styled_map_id} の取得エラー: {str(e)}")
        return None


@dataclass
class AddStyledMapOptions:
    """
    新しいスタイルマップを追加するためのオプション
    """

    name: str
    qgisproject: str


def add_styled_map(
    project_id: str, options: AddStyledMapOptions
) -> Optional[QgishubStyledMap]:
    """
    プロジェクトに新しいスタイルマップを追加する

    Args:
        project_id: プロジェクトID
        options: 新しいスタイルマップのオプション

    Returns:
        QgishubStyledMapオブジェクトまたは作成失敗時はNone
    """
    try:
        response = ApiClient.post(
            f"/project/{project_id}/styled-map",
            {
                "name": options.name,
                "qgisproject": options.qgisproject,
            },
        )
        if not response:
            return None

        return QgishubStyledMap(
            id=response.get("id", ""),
            name=response.get("name", ""),
            qgisproject=response.get("qgisproject", ""),
            isPublic=response.get("isPublic", False),
            projectId=project_id,
        )
    except Exception as e:
        print(f"プロジェクト {project_id} へのMap追加エラー: {str(e)}")
        return None


def delete_styled_map(styled_map_id: str) -> bool:
    """
    スタイルマップを削除する

    Args:
        styled_map_id: スタイルマップID

    Returns:
        成功した場合はTrue、それ以外はFalse
    """
    try:
        ApiClient.delete(f"/styled-map/{styled_map_id}")
        return True
    except Exception as e:
        print(f"Map {styled_map_id} の削除エラー: {str(e)}")
        return False


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
) -> Optional[QgishubStyledMap]:
    """
    スタイルマップを更新する

    Args:
        styled_map_id: スタイルマップID
        options: 更新オプション

    Returns:
        更新されたQgishubStyledMapオブジェクトまたは更新失敗時はNone
    """
    try:
        update_data = {}
        if options.name is not None:
            update_data["name"] = options.name
        if options.qgisproject is not None:
            update_data["qgisproject"] = options.qgisproject
        if options.isPublic is not None:
            update_data["isPublic"] = options.isPublic

        response = ApiClient.patch(
            f"/styled-map/{styled_map_id}",
            update_data,
        )

        if not response:
            return None

        return QgishubStyledMap(
            id=response.get("id", ""),
            name=response.get("name", ""),
            qgisproject=response.get("qgisproject", ""),
            isPublic=response.get("isPublic", False),
            projectId=response.get("projectId", ""),
        )
    except Exception as e:
        print(f"Map {styled_map_id} の更新エラー: {str(e)}")
        return None
