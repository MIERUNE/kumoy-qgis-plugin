from dataclasses import dataclass
from typing import Dict, Optional

from .client import ApiClient


@dataclass
class RasterUpload:
    """``POST /project/{projectId}/raster`` のレスポンス。

    メタデータ登録の結果（``raster_id``）と、COG を S3 へ送るための
    presigned POST 情報（``url`` / ``fields``）を持つ。``fields`` には S3 キーを
    含むフォームフィールド一式が入っており、そのままアップロードに渡せる。
    """

    raster_id: str
    url: str
    fields: Dict[str, str]


def create_raster(
    project_id: str,
    name: str,
    bytes: int,
    attribution: Optional[str] = None,
) -> RasterUpload:
    """Raster メタデータを登録し、COG アップロード用の presigned POST を取得する。

    Args:
        project_id: 登録先プロジェクト ID
        name: 表示名（最大 32 文字）
        bytes: アップロードする COG のサイズ（バイト）。サーバ側のストレージ
            クォータ判定に使われ、登録時に確定する（COG は immutable）。
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
        url=response.get("url", ""),
        fields=response.get("fields", {}),
    )


def delete_raster(raster_id: str) -> None:
    """Raster を削除する（アップロード失敗時のクリーンアップに使う）。"""
    ApiClient.delete(f"/raster/{raster_id}")
