"""Column type mapping in KumoyDataProvider.fields()

Falling back to bool nulls out string values, which looks like data loss.
"""

import pytest


def _fields_for(columns):
    """fields() only reads self.kumoy_vector.columns, so a stub is enough."""
    import types

    from plugin_dir.kumoy.provider.dataprovider import KumoyDataProvider

    stub = types.SimpleNamespace(kumoy_vector=types.SimpleNamespace(columns=columns))
    return KumoyDataProvider.fields(stub)


@pytest.mark.usefixtures("qgis_plugin_path")
class TestFieldTypeMapping:
    @pytest.mark.parametrize(
        ("column_type", "expected_attr"),
        [
            ("string", "String"),
            ("integer", "LongLong"),
            ("float", "Double"),
            ("boolean", "Bool"),
            ("attachment", "String"),
        ],
    )
    def test_maps_each_server_type(self, column_type, expected_attr):
        from qgis.PyQt.QtCore import QVariant

        fields = _fields_for([{"name": "c", "type": column_type}])

        idx = fields.indexOf("c")
        assert idx >= 0
        assert fields.at(idx).type() == getattr(QVariant, expected_attr)

    def test_unknown_type_falls_back_to_string_not_bool(self):
        from qgis.PyQt.QtCore import QVariant

        fields = _fields_for([{"name": "c", "type": "something_new"}])

        assert fields.at(fields.indexOf("c")).type() == QVariant.String

    def test_string_like_fields_get_a_length_limit(self):
        from plugin_dir.kumoy import constants

        fields = _fields_for(
            [
                {"name": "s", "type": "string"},
                {"name": "a", "type": "attachment"},
            ]
        )

        for name in ("s", "a"):
            field = fields.at(fields.indexOf(name))
            assert field.length() == constants.MAX_CHARACTERS_STRING_FIELD

    @pytest.mark.parametrize(
        ("column_type", "expected_type_name"),
        [
            ("string", "VARCHAR"),
            ("integer", "INTEGER"),
            ("float", "DOUBLE PRECISION"),
            ("boolean", "BOOLEAN"),
            ("attachment", "ATTACHMENT"),
        ],
    )
    def test_type_name_round_trips_the_server_type(
        self, column_type, expected_type_name
    ):
        fields = _fields_for([{"name": "c", "type": column_type}])

        assert fields.at(fields.indexOf("c")).typeName() == expected_type_name

    def test_kumoy_id_is_always_first(self):
        from qgis.PyQt.QtCore import QVariant

        fields = _fields_for([{"name": "c", "type": "attachment"}])

        assert fields.at(0).name() == "kumoy_id"
        assert fields.at(0).type() == QVariant.LongLong

    def test_no_columns_yields_only_kumoy_id(self):
        fields = _fields_for([])

        assert fields.names() == ["kumoy_id"]
