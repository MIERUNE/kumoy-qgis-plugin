from dataclasses import dataclass
from typing import List, Optional

from . import client
from ._util import UNSET, compact
from .models import PresignedPost, StyledMap, StyledMapDetail, from_dict, list_of

# Server limit on the project XML (characters)
MAX_QGISPROJECT_LENGTH = 3_000_000


def get_styled_maps(project_id: str) -> List[StyledMap]:
    return list_of(StyledMap, client.get(f"/project/{project_id}/styled-map"))


def get_styled_map(styled_map_id: str) -> StyledMapDetail:
    """The map with its QGIS project XML and the user's role."""
    data = client.post(f"/_qgis/styled-map/{styled_map_id}")
    return from_dict(StyledMapDetail, data)


def create_styled_map(
    project_id: str,
    name: str,
    qgisproject: str,
    description: str = "",
    attribution: str = "",
    isPublic: bool = False,
) -> StyledMap:
    data = client.post(
        f"/project/{project_id}/styled-map",
        {
            "name": name,
            "qgisproject": qgisproject,
            "description": description,
            "attribution": attribution,
            "isPublic": isPublic,
        },
    )
    return from_dict(StyledMap, data)


def update_styled_map(
    styled_map_id: str,
    name: Optional[str] = UNSET,
    description: Optional[str] = UNSET,
    qgisproject: Optional[str] = UNSET,
    isPublic: Optional[bool] = UNSET,
    attribution: Optional[str] = UNSET,
    assetsHash: Optional[str] = UNSET,
) -> StyledMap:
    """Update only the given fields. assetsHash=None clears the sprite hash."""
    payload = compact(
        name=name,
        description=description,
        qgisproject=qgisproject,
        isPublic=isPublic,
        attribution=attribution,
        assetsHash=assetsHash,
    )
    return from_dict(StyledMap, client.put(f"/styled-map/{styled_map_id}", payload))


def delete_styled_map(styled_map_id: str) -> None:
    client.delete(f"/styled-map/{styled_map_id}")


@dataclass
class SpriteUploadUrls:
    json: PresignedPost
    png: PresignedPost


def get_sprite_upload_urls(
    styled_map_id: str, json_file_size: int, png_file_size: int
) -> SpriteUploadUrls:
    """Presigned multipart POSTs (relative to the server, valid 30 s)."""
    data = client.post(
        f"/styled-map/{styled_map_id}/assets-upload",
        {"jsonFileSize": json_file_size, "pngFileSize": png_file_size},
    )
    return SpriteUploadUrls(
        json=from_dict(PresignedPost, data["json"]),
        png=from_dict(PresignedPost, data["png"]),
    )
