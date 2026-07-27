"""kumoy.upload.destinations のユニットテスト（APIモジュールをモックする）

アップロード先の列挙順はProcessingアルゴリズムのenumインデックスと
Map保存変換フローの逆引きで一致している必要があるため、順序を固定で検証する。
"""

from types import SimpleNamespace

import pytest


def _org(id: str, name: str, scheduled_deletion=None):
    return SimpleNamespace(id=id, name=name, scheduledDeletionAt=scheduled_deletion)


@pytest.mark.usefixtures("qgis_plugin_path")
class TestListUploadDestinations:
    def test_orders_projects_then_catalogs_per_org(self, monkeypatch):
        from plugin_dir.kumoy.upload import destinations

        monkeypatch.setattr(
            destinations.api.organization,
            "get_organizations",
            lambda: [_org("o-1", "OrgA"), _org("o-2", "OrgB")],
        )
        monkeypatch.setattr(
            destinations.api.project,
            "get_projects_by_organization",
            lambda org_id: {
                "o-1": [SimpleNamespace(id="p-1", name="Proj1")],
                "o-2": [SimpleNamespace(id="p-2", name="Proj2")],
            }[org_id],
        )
        monkeypatch.setattr(
            destinations.api.catalog,
            "get_catalogs",
            lambda org_id: {
                "o-1": [SimpleNamespace(id="c-1", name="Cat1")],
                "o-2": [],
            }[org_id],
        )

        result = destinations.list_upload_destinations()

        assert [(d.kind, d.id) for d in result] == [
            ("PROJECT", "p-1"),
            ("CATALOG", "c-1"),
            ("PROJECT", "p-2"),
        ]
        assert result[0].label == "OrgA / Proj1"
        # Catalogのラベルには種別が付記される
        assert "Cat1" in result[1].label and result[1].label != "OrgA / Cat1"

    def test_skips_organizations_scheduled_for_deletion(self, monkeypatch):
        from plugin_dir.kumoy.upload import destinations

        monkeypatch.setattr(
            destinations.api.organization,
            "get_organizations",
            lambda: [_org("o-1", "OrgA", scheduled_deletion="2026-08-01")],
        )

        def fail(org_id):
            raise AssertionError("must not be called for deleted org")

        monkeypatch.setattr(
            destinations.api.project, "get_projects_by_organization", fail
        )
        monkeypatch.setattr(destinations.api.catalog, "get_catalogs", fail)

        assert destinations.list_upload_destinations() == []


@pytest.mark.usefixtures("qgis_plugin_path")
class TestResolveRoleAndOrganization:
    def test_project_destination(self, monkeypatch):
        from plugin_dir.kumoy.upload import destinations

        organization = SimpleNamespace(id="o-1")
        monkeypatch.setattr(
            destinations.api.project,
            "get_project",
            lambda project_id: SimpleNamespace(
                role="ADMIN", team=SimpleNamespace(organizationId="o-1")
            ),
        )
        monkeypatch.setattr(
            destinations.api.organization,
            "get_organization",
            lambda org_id: organization,
        )

        role, org = destinations.resolve_role_and_organization(
            destinations.UploadDestination(kind="PROJECT", id="p-1", label="x")
        )

        assert role == "ADMIN"
        assert org is organization

    def test_catalog_destination(self, monkeypatch):
        from plugin_dir.kumoy.upload import destinations

        organization = SimpleNamespace(id="o-1")
        monkeypatch.setattr(
            destinations.api.catalog,
            "get_catalog",
            lambda catalog_id: SimpleNamespace(role="MEMBER", organizationId="o-1"),
        )
        monkeypatch.setattr(
            destinations.api.organization,
            "get_organization",
            lambda org_id: organization,
        )

        role, org = destinations.resolve_role_and_organization(
            destinations.UploadDestination(kind="CATALOG", id="c-1", label="x")
        )

        assert role == "MEMBER"
        assert org is organization
