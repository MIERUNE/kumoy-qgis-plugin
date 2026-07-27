"""Catalog（組織横断のデータ共有）関連のAPI。

Catalogは組織直下のフラットなデータ束で、Vector/RasterはProjectかCatalogの
どちらか一方に排他的に所有される。Catalogは常に所有組織全体へ公開されるため、
一覧・詳細は組織メンバーなら誰でも取得できる（編集は組織ADMIN/OWNERのみ）。
"""

from dataclasses import dataclass
from typing import List, Literal

from .client import ApiClient


@dataclass
class KumoyCatalog:
    """``GET /organization/{id}/catalogs`` の一覧の1件。"""

    id: str
    name: str
    description: str
    organizationId: str
    vectorCount: int
    rasterCount: int
    createdAt: str
    updatedAt: str


@dataclass
class CatalogVector:
    """Catalog詳細に含まれるVectorの要約。"""

    id: str
    name: str
    type: Literal["POINT", "LINESTRING", "POLYGON"]
    storageUnits: float
    createdAt: str
    updatedAt: str


@dataclass
class CatalogRaster:
    """Catalog詳細に含まれるRasterの要約。"""

    id: str
    name: str
    storageUnits: float
    createdAt: str
    updatedAt: str


@dataclass
class KumoyCatalogDetail:
    """``GET /catalog/{catalogId}`` の取得結果。

    ``role`` はCatalogの所有組織でのユーザーロールがそのまま入る
    （組織ADMIN/OWNER=編集可、MEMBER=閲覧のみ）。
    """

    id: str
    name: str
    description: str
    organizationId: str
    role: Literal["OWNER", "ADMIN", "MEMBER"]
    vectors: List[CatalogVector]
    rasters: List[CatalogRaster]
    createdAt: str
    updatedAt: str


def get_catalogs(organization_id: str) -> List[KumoyCatalog]:
    """組織のCatalog一覧を取得する。"""
    response = ApiClient.get(f"/organization/{organization_id}/catalogs")
    return [
        KumoyCatalog(
            id=item.get("id", ""),
            name=item.get("name", ""),
            description=item.get("description", ""),
            organizationId=item.get("organizationId", ""),
            vectorCount=item.get("vectorCount", 0),
            rasterCount=item.get("rasterCount", 0),
            createdAt=item.get("createdAt", ""),
            updatedAt=item.get("updatedAt", ""),
        )
        for item in response
    ]


def get_catalog(catalog_id: str) -> KumoyCatalogDetail:
    """Catalog詳細（内包するVector/Raster一覧を含む）を取得する。"""
    response = ApiClient.get(f"/catalog/{catalog_id}")
    return KumoyCatalogDetail(
        id=response.get("id", ""),
        name=response.get("name", ""),
        description=response.get("description", ""),
        organizationId=response.get("organizationId", ""),
        role=response.get("role", "MEMBER"),
        vectors=[
            CatalogVector(
                id=item.get("id", ""),
                name=item.get("name", ""),
                type=item.get("type", "POINT"),
                storageUnits=item.get("storageUnits", 0),
                createdAt=item.get("createdAt", ""),
                updatedAt=item.get("updatedAt", ""),
            )
            for item in response.get("vectors", [])
        ],
        rasters=[
            CatalogRaster(
                id=item.get("id", ""),
                name=item.get("name", ""),
                storageUnits=item.get("storageUnits", 0),
                createdAt=item.get("createdAt", ""),
                updatedAt=item.get("updatedAt", ""),
            )
            for item in response.get("rasters", [])
        ],
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
    )
