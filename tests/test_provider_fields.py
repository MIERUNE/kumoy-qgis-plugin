"""KumoyDataProvider.fields() のカラム型マッピングのテスト

サーバのカラム型が増えたとき、未知の型を bool に落とすと文字列値が NULL 化されて
「データが消えた」ように見える（attachment 型の追加時に実際に起きた）。
型ごとの対応と、未知の型が安全側（string）に倒れることを固定する。
"""

import pytest


def _fields_for(columns):
    """カラム定義から fields() の結果を得る（プロバイダ本体は組み立てない）。

    fields() はネットワークにも gisdb にも触らず self.kumoy_vector.columns だけを見る
    ため、その一点だけを差し込んだ最小のオブジェクトで呼べる。
    """
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
            # 添付はファイル名の文字列。bool にすると値が消える
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

        # 将来サーバに型が増えても、値をそのまま持てる string に倒れること
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

    def test_kumoy_id_is_always_first(self):
        from qgis.PyQt.QtCore import QVariant

        fields = _fields_for([{"name": "c", "type": "attachment"}])

        assert fields.at(0).name() == "kumoy_id"
        assert fields.at(0).type() == QVariant.LongLong

    def test_no_columns_yields_only_kumoy_id(self):
        fields = _fields_for([])

        assert fields.names() == ["kumoy_id"]
