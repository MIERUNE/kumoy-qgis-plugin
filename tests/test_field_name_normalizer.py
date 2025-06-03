import os
import sys
import unittest
from typing import List
from unittest.mock import Mock

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Register package name in sys.modules to recognize it as a package
package_name = os.path.basename(project_root)
if package_name not in sys.modules:
    import types

    package_module = types.ModuleType(package_name)
    package_module.__path__ = [project_root]
    sys.modules[package_name] = package_module

# Direct import to avoid loading provider
import importlib.util

spec = importlib.util.spec_from_file_location(
    "field_name_normalizer",
    os.path.join(project_root, "processing", "field_name_normalizer.py"),
)
field_name_normalizer_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(field_name_normalizer_module)
FieldNameNormalizer = field_name_normalizer_module.FieldNameNormalizer


class TestFieldNameNormalizer(unittest.TestCase):
    """Unit tests for FieldNameNormalizer class"""

    def create_mock_field(
        self, name: str, type_name="String", field_type=10
    ) -> Mock:  # 10 = String
        """Create a mock field"""
        field = Mock()
        field.name.return_value = name
        field.typeName.return_value = type_name
        field.type.return_value = field_type
        return field

    def create_mock_layer(self, field_names: List[str], field_types=None) -> Mock:
        """Create a mock layer"""
        if field_types is None:
            field_types = ["String"] * len(field_names)

        mock_layer = Mock()
        mock_fields = Mock()

        # Mock fields() method
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
        """Test simple normalization"""
        layer = self.create_mock_layer(["name", "address", "tel"])
        normalizer = FieldNameNormalizer(layer)

        # Check normalized field names
        # No changes so get_normalize_mappings is empty
        self.assertEqual(len(normalizer.normalized_to_original), 3)
        self.assertEqual(normalizer.normalized_to_original["name"], "name")
        self.assertEqual(normalizer.normalized_to_original["address"], "address")
        self.assertEqual(normalizer.normalized_to_original["tel"], "tel")

    def test_japanese_field_normalization(self):
        """Test Japanese field name normalization"""
        layer = self.create_mock_layer(["防火準防火", "当初決定日", "最終告示日"])
        normalizer = FieldNameNormalizer(layer)

        # Japanese characters are removed and become default names
        self.assertEqual(normalizer.field_name_mapping["防火準防火"], "field_1")
        self.assertEqual(normalizer.field_name_mapping["当初決定日"], "field_2")
        self.assertEqual(normalizer.field_name_mapping["最終告示日"], "field_3")

    def test_special_characters_normalization(self):
        """Test special character normalization"""
        layer = self.create_mock_layer(["field-name", "field name", "field.name"])
        normalizer = FieldNameNormalizer(layer)

        self.assertEqual(normalizer.field_name_mapping["field-name"], "field_name")
        self.assertEqual(normalizer.field_name_mapping["field name"], "field_name_1")
        self.assertEqual(normalizer.field_name_mapping["field.name"], "field_name_2")

    def test_reserved_keywords(self):
        """Test PostgreSQL reserved keywords"""
        layer = self.create_mock_layer(["select", "from", "where"])
        normalizer = FieldNameNormalizer(layer)

        self.assertEqual(normalizer.field_name_mapping["select"], "select_")
        self.assertEqual(normalizer.field_name_mapping["from"], "from_")
        self.assertEqual(normalizer.field_name_mapping["where"], "where_")

    def test_numeric_prefix(self):
        """Test field names starting with numbers"""
        layer = self.create_mock_layer(["123field", "1_field"])
        normalizer = FieldNameNormalizer(layer)

        # Numbers are removed and become 'field'
        self.assertEqual(normalizer.field_name_mapping["123field"], "field")
        self.assertEqual(normalizer.field_name_mapping["1_field"], "_field")

    def test_get_normalized_fields(self):
        """Test getting normalized fields"""
        layer = self.create_mock_layer(["name", "防火準防火", "select", "123field"])
        normalizer = FieldNameNormalizer(layer)

        # Verify field mapping is created correctly
        self.assertEqual(normalizer.field_name_mapping["name"], "name")
        self.assertEqual(normalizer.field_name_mapping["防火準防火"], "field_1")
        self.assertEqual(normalizer.field_name_mapping["select"], "select_")
        self.assertEqual(normalizer.field_name_mapping["123field"], "field")

    def test_get_skipped_fields(self):
        """Test skipped fields"""
        layer = self.create_mock_layer(
            ["name", "id", "count"], ["String", "Integer64", "String"]
        )
        normalizer = FieldNameNormalizer(layer)

        # Integer64 type fields are not included in normalized_columns
        self.assertIn("name", normalizer._normalized_columns)
        self.assertNotIn("id", normalizer._normalized_columns)
        self.assertIn("count", normalizer._normalized_columns)

    def test_empty_layer(self):
        """Test empty layer"""
        layer = self.create_mock_layer([])
        normalizer = FieldNameNormalizer(layer)

        # get_normalized_fields() returns QgsFields, so check length
        self.assertEqual(len(normalizer.get_normalized_fields()), 0)
        self.assertEqual(len(normalizer._normalized_columns), 0)

    def test_duplicate_handling(self):
        """Test duplicate field name handling"""
        # Cases where names become the same after normalization
        layer = self.create_mock_layer(
            ["field", "Field", "FIELD", "field-name", "field_name"]
        )
        normalizer = FieldNameNormalizer(layer)

        # Verify duplicate handling
        self.assertEqual(normalizer.field_name_mapping["field"], "field")
        self.assertEqual(normalizer.field_name_mapping["Field"], "field_1")
        self.assertEqual(normalizer.field_name_mapping["FIELD"], "field_2")
        self.assertEqual(normalizer.field_name_mapping["field-name"], "field_name")
        self.assertEqual(normalizer.field_name_mapping["field_name"], "field_name_1")

    def test_length_truncation(self):
        """Test field name length truncation (63 character limit)"""
        # Test various long field names
        layer = self.create_mock_layer(
            [
                "a" * 63,  # Exactly 63 chars - should not be truncated
                "b" * 64,  # 64 chars - should be truncated
                "very_long_field_name_that_exceeds_postgresql_maximum_identifier_length_limit",  # 77 chars
                "this_is_a_really_long_field_name_with_many_words_that_exceeds_the_limit_of_63",  # 78 chars
                "x" * 100,  # 100 chars
                "field_" * 20,  # 120 chars (field_ repeated 20 times)
            ]
        )
        normalizer = FieldNameNormalizer(layer)

        # 63 characters - should not be truncated
        self.assertEqual(normalizer.field_name_mapping["a" * 63], "a" * 63)
        self.assertEqual(len(normalizer.field_name_mapping["a" * 63]), 63)

        # 64 characters - should be truncated to 63
        self.assertEqual(normalizer.field_name_mapping["b" * 64], "b" * 63)
        self.assertEqual(len(normalizer.field_name_mapping["b" * 64]), 63)

        # 77 characters - should be truncated to 63
        long_name_77 = "very_long_field_name_that_exceeds_postgresql_maximum_identifier_length_limit"
        expected_77 = "very_long_field_name_that_exceeds_postgresql_maximum_identifier"
        self.assertEqual(normalizer.field_name_mapping[long_name_77], expected_77)
        self.assertEqual(len(normalizer.field_name_mapping[long_name_77]), 63)

        # 78 characters - should be truncated to 63
        long_name_78 = "this_is_a_really_long_field_name_with_many_words_that_exceeds_the_limit_of_63"
        truncated_78 = normalizer.field_name_mapping[long_name_78]
        self.assertEqual(len(truncated_78), 63)
        self.assertEqual(truncated_78, long_name_78[:63])  # Should be first 63 chars

        # 100 characters - should be truncated to 63
        self.assertEqual(normalizer.field_name_mapping["x" * 100], "x" * 63)
        self.assertEqual(len(normalizer.field_name_mapping["x" * 100]), 63)

        # 120 characters - should be truncated to 63
        long_name_120 = "field_" * 20
        truncated_120 = normalizer.field_name_mapping[long_name_120]
        self.assertEqual(len(truncated_120), 63)
        self.assertEqual(truncated_120, long_name_120[:63])  # Should be first 63 chars

    def test_length_truncation_with_duplicates(self):
        """Test length truncation with duplicate handling"""
        # Test when truncated names become duplicates
        layer = self.create_mock_layer(
            [
                "a" * 70,  # Will be truncated to "aaa...aaa" (63 chars)
                "a"
                * 80,  # Will also be truncated to "aaa...aaa" (63 chars) - duplicate!
                "a" * 90,  # Another duplicate after truncation
                "very_long_field_name_that_will_be_truncated_to_exactly_63_characters_here",
                "very_long_field_name_that_will_be_truncated_to_exactly_63_characters_different",
            ]
        )
        normalizer = FieldNameNormalizer(layer)

        # First long name gets truncated to 63 chars
        self.assertEqual(normalizer.field_name_mapping["a" * 70], "a" * 63)

        # Second long name with same prefix gets truncated and numbered
        # Since "aaa...aaa" (63 chars) is taken, it becomes "aaa...aaa_1" but that's too long
        # So it should be truncated further to accommodate the suffix
        second_name = normalizer.field_name_mapping["a" * 80]
        self.assertNotEqual(second_name, "a" * 63)  # Should be different
        self.assertLessEqual(len(second_name), 63)  # Should not exceed limit
        self.assertTrue(second_name.endswith("_1"))  # Should have suffix

        # Third duplicate
        third_name = normalizer.field_name_mapping["a" * 90]
        self.assertNotEqual(third_name, "a" * 63)  # Should be different
        self.assertNotEqual(third_name, second_name)  # Should be different from second
        self.assertLessEqual(len(third_name), 63)  # Should not exceed limit
        self.assertTrue(third_name.endswith("_2"))  # Should have suffix

        # Long names that become the same after truncation
        name1 = (
            "very_long_field_name_that_will_be_truncated_to_exactly_63_characters_here"
        )
        name2 = "very_long_field_name_that_will_be_truncated_to_exactly_63_characters_different"
        truncated1 = normalizer.field_name_mapping[name1]
        truncated2 = normalizer.field_name_mapping[name2]

        # Both should be truncated
        self.assertEqual(len(truncated1), 63)
        self.assertLessEqual(len(truncated2), 63)

        # They should be different (second one gets a suffix)
        self.assertNotEqual(truncated1, truncated2)

    def test_feedback_messages(self):
        """Test feedback messages"""
        layer = self.create_mock_layer(
            ["防火準防火", "select", "id"], ["String", "String", "Integer64"]
        )

        # Mock feedback object
        feedback = Mock()
        feedback.pushInfo = Mock()
        feedback.pushWarning = Mock()

        FieldNameNormalizer(layer, feedback)

        # Verify pushInfo was called
        feedback.pushInfo.assert_called()
        feedback.pushWarning.assert_called()

        # Verify normalization and skip messages were output
        info_calls = feedback.pushInfo.call_args_list
        warning_calls = feedback.pushWarning.call_args_list

        info_messages = [call[0][0] for call in info_calls]
        warning_messages = [call[0][0] for call in warning_calls]

        # Verify normalization messages
        self.assertTrue(
            any(
                "normalized for PostgreSQL compatibility" in msg
                for msg in info_messages
            )
        )
        # Verify skip messages
        self.assertTrue(
            any(
                "skipped due to unsupported data types" in msg
                for msg in warning_messages
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
