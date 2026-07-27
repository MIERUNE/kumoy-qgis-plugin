"""kumoy/provider/dataprovider の parse_uri のテスト

Catalog対応で所有元キーが project_id / catalog_id の排他になったため、
両方の受理と、所有元なし・vector_idなしの拒否を検証する。
"""

import pytest


@pytest.fixture(scope="module")
def registered_metadata(qgis_app):
    from qgis.core import QgsProviderRegistry

    from plugin_dir.kumoy.provider.dataprovider_metadata import KumoyProviderMetadata

    # 同一キーの二重登録は False になるだけで無害（他テストとの実行順に依存しない）。
    QgsProviderRegistry.instance().registerProvider(KumoyProviderMetadata())


@pytest.mark.usefixtures("qgis_plugin_path", "registered_metadata")
class TestParseUri:
    def _fn(self):
        from plugin_dir.kumoy.provider.dataprovider import parse_uri

        return parse_uri

    def test_parses_project_owned(self):
        project_id, catalog_id, vector_id, vector_name, subset = self._fn()(
            "project_id=p-1;vector_id=v-2;vector_name=roads;vector_type=LINESTRING;"
        )
        assert project_id == "p-1"
        assert catalog_id == ""
        assert vector_id == "v-2"
        assert vector_name == "roads"
        assert subset == ""

    def test_parses_catalog_owned(self):
        project_id, catalog_id, vector_id, vector_name, subset = self._fn()(
            "catalog_id=c-1;vector_id=v-2;vector_name=roads;vector_type=LINESTRING;"
        )
        assert project_id == ""
        assert catalog_id == "c-1"
        assert vector_id == "v-2"
        assert vector_name == "roads"

    def test_keeps_subset_with_semicolons(self):
        _, _, _, _, subset = self._fn()(
            'catalog_id=c-1;vector_id=v-2;vector_name=roads;subset="a";"b"'
        )
        assert subset == '"a";"b"'

    def test_raises_without_vector_id(self):
        with pytest.raises(ValueError):
            self._fn()("project_id=p-1;vector_name=roads;")

    def test_raises_without_owner(self):
        # vector_id があっても所有元（project_id/catalog_id）が無ければ不正
        with pytest.raises(ValueError):
            self._fn()("vector_id=v-2;vector_name=roads;")
