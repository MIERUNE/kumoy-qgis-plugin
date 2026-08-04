"""Add-field round trip: QGIS's dialog only carries the server type in typeName.

If ATTACHMENT is lost there, the new column silently becomes a plain string field.
"""

import types

import pytest


@pytest.mark.usefixtures("qgis_plugin_path")
class TestAddAttributes:
    @pytest.fixture
    def sent(self, monkeypatch):
        from plugin_dir.kumoy import api

        captured = {}

        def fake_add_attributes(vector_id, attributes):
            captured.update(vector_id=vector_id, attributes=attributes)

        monkeypatch.setattr(api.qgis_vector, "add_attributes", fake_add_attributes)
        return captured

    def _add(self, fields):
        from plugin_dir.kumoy.provider.dataprovider import KumoyDataProvider

        stub = types.SimpleNamespace(
            kumoy_vector=types.SimpleNamespace(id="vector-1"),
            _reload_vector=lambda: None,
        )
        return KumoyDataProvider.addAttributes(stub, fields)

    def test_attachment_is_offered_as_its_own_native_type(self):
        from qgis.PyQt.QtCore import QVariant

        from plugin_dir.kumoy.provider.dataprovider import _native_types

        attachment = [t for t in _native_types() if t.mTypeName == "ATTACHMENT"]

        assert len(attachment) == 1
        assert attachment[0].mType == QVariant.String
        # Length 0 comes out of the dialog when the user leaves it alone
        assert attachment[0].mMinLen == 0

    @pytest.mark.parametrize(
        ("type_name", "expected"),
        [
            ("ATTACHMENT", "attachment"),
            ("VARCHAR", "string"),
            ("INTEGER", "integer"),
            ("DOUBLE PRECISION", "float"),
            ("BOOLEAN", "boolean"),
        ],
    )
    def test_type_name_decides_the_server_type(self, sent, type_name, expected):
        from qgis.core import QgsField
        from qgis.PyQt.QtCore import QVariant

        field = QgsField("c", QVariant.String)
        field.setTypeName(type_name)

        assert self._add([field]) is True
        assert sent["attributes"] == [{"name": "c", "type": expected}]

    def test_falls_back_to_qvariant_when_type_name_is_unset(self, sent):
        from qgis.core import QgsField
        from qgis.PyQt.QtCore import QVariant

        assert self._add([QgsField("c", QVariant.LongLong)]) is True
        assert sent["attributes"] == [{"name": "c", "type": "integer"}]
