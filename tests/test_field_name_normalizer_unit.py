import os
import sys
import unittest
from typing import List
from unittest.mock import Mock

# プロジェクトルートをパスに追加
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# パッケージ名をsys.modulesに登録してパッケージとして認識させる
package_name = os.path.basename(project_root)
if package_name not in sys.modules:
    import types

    package_module = types.ModuleType(package_name)
    package_module.__path__ = [project_root]
    sys.modules[package_name] = package_module

# 直接インポートしてproviderの読み込みを回避
import importlib.util

spec = importlib.util.spec_from_file_location(
    "field_name_normalizer",
    os.path.join(project_root, "processing", "field_name_normalizer.py"),
)
field_name_normalizer_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(field_name_normalizer_module)
FieldNameNormalizer = field_name_normalizer_module.FieldNameNormalizer


class TestFieldNameNormalizer(unittest.TestCase):
    """FieldNameNormalizerクラスのユニットテスト"""

    def create_mock_field(
        self, name: str, type_name="String", field_type=10
    ) -> Mock:  # 10 = String
        """モックフィールドを作成"""
        field = Mock()
        field.name.return_value = name
        field.typeName.return_value = type_name
        field.type.return_value = field_type
        return field

    def create_mock_layer(self, field_names: List[str], field_types=None) -> Mock:
        """モックレイヤーを作成"""
        if field_types is None:
            field_types = ["String"] * len(field_names)

        mock_layer = Mock()
        mock_fields = Mock()

        # fields()メソッドをモック
        fields = []
        for name, type_name in zip(field_names, field_types):
            if type_name == "String":
                field_type = 10
            elif type_name == "Integer":
                field_type = 2
            elif type_name == "Integer64":
                field_type = 4  # LongLong
            else:
                field_type = 10  # Default to String
            fields.append(self.create_mock_field(name, type_name, field_type))

        mock_fields.__iter__ = Mock(return_value=iter(fields))
        mock_layer.fields.return_value = mock_fields

        return mock_layer

    def test_simple_normalization(self):
        """シンプルな正規化のテスト"""
        layer = self.create_mock_layer(["name", "address", "tel"])
        normalizer = FieldNameNormalizer(layer)

        # 正規化後のフィールド名を確認
        # 変更されていないのでget_normalize_mappingsは空
        self.assertEqual(len(normalizer.normalized_to_original), 3)
        self.assertEqual(normalizer.normalized_to_original["name"], "name")
        self.assertEqual(normalizer.normalized_to_original["address"], "address")
        self.assertEqual(normalizer.normalized_to_original["tel"], "tel")

    def test_japanese_field_normalization(self):
        """日本語フィールド名の正規化テスト"""
        layer = self.create_mock_layer(["防火準防火", "当初決定日", "最終告示日"])
        normalizer = FieldNameNormalizer(layer)

        # 日本語は削除されてデフォルト名になる
        self.assertEqual(normalizer.field_name_mapping["防火準防火"], "field_1")
        self.assertEqual(normalizer.field_name_mapping["当初決定日"], "field_2")
        self.assertEqual(normalizer.field_name_mapping["最終告示日"], "field_3")

    def test_special_characters_normalization(self):
        """特殊文字の正規化テスト"""
        layer = self.create_mock_layer(["field-name", "field name", "field.name"])
        normalizer = FieldNameNormalizer(layer)

        self.assertEqual(normalizer.field_name_mapping["field-name"], "field_name")
        self.assertEqual(normalizer.field_name_mapping["field name"], "field_name_1")
        self.assertEqual(normalizer.field_name_mapping["field.name"], "field_name_2")

    def test_reserved_keywords(self):
        """PostgreSQL予約語のテスト"""
        layer = self.create_mock_layer(["select", "from", "where"])
        normalizer = FieldNameNormalizer(layer)

        self.assertEqual(normalizer.field_name_mapping["select"], "select_")
        self.assertEqual(normalizer.field_name_mapping["from"], "from_")
        self.assertEqual(normalizer.field_name_mapping["where"], "where_")

    def test_numeric_prefix(self):
        """数字で始まるフィールド名のテスト"""
        layer = self.create_mock_layer(["123field", "1_field"])
        normalizer = FieldNameNormalizer(layer)

        # 数字が削除されてfieldになる
        self.assertEqual(normalizer.field_name_mapping["123field"], "field")
        self.assertEqual(normalizer.field_name_mapping["1_field"], "_field")

    def test_get_normalized_fields(self):
        """正規化されたフィールドの取得テスト"""
        layer = self.create_mock_layer(["name", "防火準防火", "select", "123field"])
        normalizer = FieldNameNormalizer(layer)

        # フィールドマッピングが正しく作成されているか確認
        self.assertEqual(normalizer.field_name_mapping["name"], "name")
        self.assertEqual(normalizer.field_name_mapping["防火準防火"], "field_1")
        self.assertEqual(normalizer.field_name_mapping["select"], "select_")
        self.assertEqual(normalizer.field_name_mapping["123field"], "field")

    def test_get_skipped_fields(self):
        """スキップされたフィールドのテスト"""
        layer = self.create_mock_layer(
            ["name", "id", "count"], ["String", "Integer64", "String"]
        )
        normalizer = FieldNameNormalizer(layer)

        # Integer64型のフィールドはnormalized_columnsに含まれない
        self.assertIn("name", normalizer._normalized_columns)
        self.assertNotIn("id", normalizer._normalized_columns)
        self.assertIn("count", normalizer._normalized_columns)

    def test_empty_layer(self):
        """空のレイヤーのテスト"""
        layer = self.create_mock_layer([])
        normalizer = FieldNameNormalizer(layer)

        # get_normalized_fields()はQgsFieldsを返すので、長さを確認
        self.assertEqual(len(normalizer.get_normalized_fields()), 0)
        self.assertEqual(len(normalizer._normalized_columns), 0)

    def test_duplicate_handling(self):
        """重複フィールド名の処理テスト"""
        # 正規化後に同じ名前になるケース
        layer = self.create_mock_layer(
            ["field", "Field", "FIELD", "field-name", "field_name"]
        )
        normalizer = FieldNameNormalizer(layer)

        # 重複時の処理を確認
        self.assertEqual(normalizer.field_name_mapping["field"], "field")
        self.assertEqual(normalizer.field_name_mapping["Field"], "field_1")
        self.assertEqual(normalizer.field_name_mapping["FIELD"], "field_2")
        self.assertEqual(normalizer.field_name_mapping["field-name"], "field_name")
        self.assertEqual(normalizer.field_name_mapping["field_name"], "field_name_1")

    def test_feedback_messages(self):
        """フィードバックメッセージのテスト"""
        layer = self.create_mock_layer(
            ["防火準防火", "select", "id"], ["String", "String", "Integer64"]
        )

        # モックのフィードバックオブジェクト
        feedback = Mock()
        feedback.pushInfo = Mock()
        feedback.pushWarning = Mock()

        normalizer = FieldNameNormalizer(layer, feedback)

        # pushInfoが呼ばれたことを確認
        feedback.pushInfo.assert_called()
        feedback.pushWarning.assert_called()

        # 正規化とスキップのメッセージが出力されたことを確認
        info_calls = feedback.pushInfo.call_args_list
        warning_calls = feedback.pushWarning.call_args_list

        info_messages = [call[0][0] for call in info_calls]
        warning_messages = [call[0][0] for call in warning_calls]

        # 正規化メッセージの確認
        self.assertTrue(
            any(
                "normalized for PostgreSQL compatibility" in msg
                for msg in info_messages
            )
        )
        # スキップメッセージの確認
        self.assertTrue(
            any(
                "skipped due to unsupported data types" in msg
                for msg in warning_messages
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
