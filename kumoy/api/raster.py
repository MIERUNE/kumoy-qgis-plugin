from dataclasses import dataclass
from typing import Dict, List, Literal, Optional

from .client import ApiClient


@dataclass
class KumoyRaster:
    """プロジェクト内のラスタ一覧の1件。"""

    id: str
    name: str
    projectId: str
    attribution: str
    bytes: int
    createdAt: str
    updatedAt: str


@dataclass
class KumoyRasterDetail(KumoyRaster):
    """``GET /raster/{rasterId}`` の単体取得結果。一覧に加えて ``role`` を持つ。"""

    role: Literal["OWNER", "ADMIN", "MEMBER"]


def get_rasters(project_id: str) -> List[KumoyRaster]:
    """プロジェクトのラスタ一覧を取得する。"""
    response = ApiClient.get(f"/project/{project_id}/raster")
    return [
        KumoyRaster(
            id=item.get("id", ""),
            name=item.get("name", ""),
            projectId=item.get("projectId", ""),
            attribution=item.get("attribution", ""),
            bytes=item.get("bytes", 0),
            createdAt=item.get("createdAt", ""),
            updatedAt=item.get("updatedAt", ""),
        )
        for item in response
    ]


def get_raster(raster_id: str) -> KumoyRasterDetail:
    """ラスタ単体のメタデータを取得する。"""
    response = ApiClient.get(f"/raster/{raster_id}")
    return KumoyRasterDetail(
        id=response.get("id", ""),
        name=response.get("name", ""),
        projectId=response.get("projectId", ""),
        attribution=response.get("attribution", ""),
        bytes=response.get("bytes", 0),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
        role=response.get("role", "MEMBER"),
    )


def get_download_url(raster_id: str) -> str:
    """COG を S3 から取得するための presigned GET URL を発行する。

    返る URL は署名済みの絶対 URL で、認証ヘッダ無しでそのまま GET できる。
    短時間で失効するため、ダウンロード直前に都度取得する（保存・使い回ししない）。
    """
    response = ApiClient.get(f"/raster/{raster_id}/download")
    return response.get("url", "")


@dataclass
class RasterUpload:
    """``POST /project/{projectId}/raster`` のレスポンス。

    メタデータ登録の結果（``raster_id``）と、COG を S3 へ送るための presigned
    POST 情報（``upload_url`` / ``upload_fields``）を持つ。``upload_url`` は S3
    バケットのエンドポイント、``upload_fields`` は multipart/form-data として
    ファイルの前に並べる署名フィールド群（``key`` や ``Policy`` 等）。S3 側で
    ファイルサイズ上限が強制されるため、申告 ``bytes`` を超えると 400 で拒否される。
    """

    raster_id: str
    upload_url: str
    upload_fields: Dict[str, str]


def create_raster(
    project_id: str,
    name: str,
    bytes: int,
    attribution: Optional[str] = None,
) -> RasterUpload:
    """Raster メタデータを登録し、COG アップロード用の presigned POST 情報を取得する。

    Args:
        project_id: 登録先プロジェクト ID
        name: 表示名（最大 32 文字）
        bytes: アップロードする COG のサイズ（バイト）。サーバ側のストレージ
            クォータ判定に使われ、登録時に確定する（COG は immutable）。
            申告値より大きいファイルは S3 が 400 で拒否する。
        attribution: 出典表記（任意）

    Raises:
        QuotaExceededError: プランの上限超過時（429）。
    """
    payload: Dict[str, object] = {"name": name, "bytes": bytes}
    if attribution is not None:
        payload["attribution"] = attribution

    response = ApiClient.post(f"/project/{project_id}/raster", payload)

    return RasterUpload(
        raster_id=response.get("rasterId", ""),
        upload_url=response.get("uploadUrl", ""),
        upload_fields=response.get("uploadFields", {}),
    )


def delete_raster(raster_id: str) -> None:
    """Raster を削除する（アップロード失敗時のクリーンアップに使う）。"""
    ApiClient.delete(f"/raster/{raster_id}")
