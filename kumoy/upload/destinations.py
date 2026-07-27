"""アップロード先（Project / Catalog）の列挙と解決。

Vector/RasterのアップロードはProjectに加えてCatalog（組織直下のデータ束、
組織ADMIN/OWNERのみ書き込み可）を宛先に選べる。宛先リストは
Processingアルゴリズムのenum選択肢になり、Map保存時の変換フロー
（ui/layers/convert_vector.py 等）はそのenumインデックスを逆引きするため、
列挙の順序・フィルタが両者で一致するようここへ集約する。
"""

from dataclasses import dataclass
from typing import List, Literal, Tuple

from ... import i18n
from .. import api


@dataclass
class UploadDestination:
    kind: Literal["PROJECT", "CATALOG"]
    id: str
    label: str


def list_upload_destinations() -> List[UploadDestination]:
    """ログインユーザーが到達可能なアップロード先を列挙する。

    組織ごとにProject、続いてCatalogを並べる。書き込み権限はここでは
    確認しない（実行時に resolve_role_and_organization で検証する）。
    """
    destinations: List[UploadDestination] = []
    for org in api.organization.get_organizations():
        # Organizations scheduled for deletion are unusable; their
        # project APIs return not found
        if org.scheduledDeletionAt:
            continue
        for project in api.project.get_projects_by_organization(org.id):
            destinations.append(
                UploadDestination(
                    kind="PROJECT",
                    id=project.id,
                    label=f"{org.name} / {project.name}",
                )
            )
        for catalog in api.catalog.get_catalogs(org.id):
            destinations.append(
                UploadDestination(
                    kind="CATALOG",
                    id=catalog.id,
                    label=f"{org.name} / {catalog.name} ({i18n.tr('Catalog')})",
                )
            )
    return destinations


def resolve_role_and_organization(
    destination: UploadDestination,
) -> Tuple[str, "api.organization.OrganizationDetail"]:
    """宛先での実効ロールと所属組織（プラン上限判定用）を解決する。

    Projectは所属チームでのロール、Catalogは所有組織でのロールが返る。
    どちらも書き込みには ADMIN / OWNER が必要。
    """
    if destination.kind == "PROJECT":
        project = api.project.get_project(destination.id)
        organization = api.organization.get_organization(project.team.organizationId)
        return project.role, organization

    catalog = api.catalog.get_catalog(destination.id)
    organization = api.organization.get_organization(catalog.organizationId)
    return catalog.role, organization
