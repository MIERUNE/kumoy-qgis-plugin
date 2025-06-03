from typing import List
from unittest.mock import Mock

import pytest

# FieldNameNormalizer will be available due to conftest.py's sys.path setup
from processing.field_name_normalizer import FieldNameNormalizer


class MockField:
    """Mock QgsField for testing"""

    def __init__(self, name: str, type_name: str = "String", field_type: int = 10):
        self._name = name
        self._type_name = type_name
        self._type = field_type

    def name(self) -> str:
        return self._name

    def typeName(self) -> str:
        return self._type_name

    def type(self) -> int:
        return self._type


class MockFields:
    """Mock QgsFields for testing"""

    def __init__(self, fields: List[MockField]):
        self._fields = fields

    def __iter__(self):
        return iter(self._fields)


@pytest.fixture
def create_mock_layer():
    """Fixture to create a mock layer with fields"""

    def _create_layer(field_names: List[str], field_types: List[str] = None) -> Mock:
        if field_types is None:
            field_types = ["String"] * len(field_names)

        mock_layer = Mock()

        # Map type names to QMetaType values
        type_map = {
            "String": 10,  # QString
            "Integer": 2,  # Int
            "Integer64": 4,  # LongLong
            "Double": 6,  # Double
            "Boolean": 1,  # Bool
        }

        fields = []
        for name, type_name in zip(field_names, field_types):
            field_type = type_map.get(type_name, 10)  # Default to String
            fields.append(MockField(name, type_name, field_type))

        mock_fields = MockFields(fields)
        mock_layer.fields.return_value = mock_fields

        return mock_layer

    return _create_layer


@pytest.fixture
def mock_feedback():
    """Fixture to create a mock feedback object"""
    feedback = Mock()
    feedback.pushInfo = Mock()
    feedback.pushWarning = Mock()
    return feedback


def test_simple_normalization(create_mock_layer):
    """Test simple normalization"""
    layer = create_mock_layer(["name", "address", "tel"])
    normalizer = FieldNameNormalizer(layer)

    # Check normalized field names
    # No changes so field_name_mapping should be empty or contain unchanged names
    assert len(normalizer.normalized_to_original) == 3
    assert normalizer.normalized_to_original["name"] == "name"
    assert normalizer.normalized_to_original["address"] == "address"
    assert normalizer.normalized_to_original["tel"] == "tel"


def test_japanese_field_normalization(create_mock_layer):
    """Test Japanese field name normalization"""
    layer = create_mock_layer(["防火準防火", "当初決定日", "最終告示日"])
    normalizer = FieldNameNormalizer(layer)

    # Japanese characters are removed and become default names
    assert normalizer.field_name_mapping["防火準防火"] == "field_1"
    assert normalizer.field_name_mapping["当初決定日"] == "field_2"
    assert normalizer.field_name_mapping["最終告示日"] == "field_3"


def test_special_characters_normalization(create_mock_layer):
    """Test special character normalization"""
    layer = create_mock_layer(["field-name", "field name", "field.name"])
    normalizer = FieldNameNormalizer(layer)

    assert normalizer.field_name_mapping["field-name"] == "field_name"
    assert normalizer.field_name_mapping["field name"] == "field_name_1"
    assert normalizer.field_name_mapping["field.name"] == "field_name_2"


def test_reserved_keywords(create_mock_layer):
    """Test PostgreSQL reserved keywords"""
    layer = create_mock_layer(["select", "from", "where"])
    normalizer = FieldNameNormalizer(layer)

    assert normalizer.field_name_mapping["select"] == "select_"
    assert normalizer.field_name_mapping["from"] == "from_"
    assert normalizer.field_name_mapping["where"] == "where_"


def test_numeric_prefix(create_mock_layer):
    """Test field names starting with numbers"""
    layer = create_mock_layer(["123field", "1_field"])
    normalizer = FieldNameNormalizer(layer)

    # Numbers are removed and become 'field'
    assert normalizer.field_name_mapping["123field"] == "field"
    assert normalizer.field_name_mapping["1_field"] == "_field"


def test_get_normalized_fields(create_mock_layer):
    """Test getting normalized fields"""
    layer = create_mock_layer(["name", "防火準防火", "select", "123field"])
    normalizer = FieldNameNormalizer(layer)

    # Verify field mapping is created correctly
    assert normalizer.field_name_mapping["name"] == "name"
    assert normalizer.field_name_mapping["防火準防火"] == "field_1"
    assert normalizer.field_name_mapping["select"] == "select_"
    assert normalizer.field_name_mapping["123field"] == "field"


def test_get_skipped_fields(create_mock_layer):
    """Test skipped fields"""
    layer = create_mock_layer(
        ["name", "id", "count"], ["String", "Integer64", "String"]
    )
    normalizer = FieldNameNormalizer(layer)

    # Integer64 type fields are not included in normalized_columns
    assert "name" in normalizer._normalized_columns
    assert "id" not in normalizer._normalized_columns
    assert "count" in normalizer._normalized_columns


def test_empty_layer(create_mock_layer):
    """Test empty layer"""
    layer = create_mock_layer([])
    normalizer = FieldNameNormalizer(layer)

    # get_normalized_fields() returns QgsFields, so check length
    assert len(normalizer.get_normalized_fields()) == 0
    assert len(normalizer._normalized_columns) == 0


def test_duplicate_handling(create_mock_layer):
    """Test duplicate field name handling"""
    # Cases where names become the same after normalization
    layer = create_mock_layer(["field", "Field", "FIELD", "field-name", "field_name"])
    normalizer = FieldNameNormalizer(layer)

    # Verify duplicate handling
    assert normalizer.field_name_mapping["field"] == "field"
    assert normalizer.field_name_mapping["Field"] == "field_1"
    assert normalizer.field_name_mapping["FIELD"] == "field_2"
    assert normalizer.field_name_mapping["field-name"] == "field_name"
    assert normalizer.field_name_mapping["field_name"] == "field_name_1"


def test_length_truncation(create_mock_layer):
    """Test field name length truncation (63 character limit)"""
    # Test various long field names
    layer = create_mock_layer(
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
    assert normalizer.field_name_mapping["a" * 63] == "a" * 63
    assert len(normalizer.field_name_mapping["a" * 63]) == 63

    # 64 characters - should be truncated to 63
    assert normalizer.field_name_mapping["b" * 64] == "b" * 63
    assert len(normalizer.field_name_mapping["b" * 64]) == 63

    # 77 characters - should be truncated to 63
    long_name_77 = (
        "very_long_field_name_that_exceeds_postgresql_maximum_identifier_length_limit"
    )
    expected_77 = "very_long_field_name_that_exceeds_postgresql_maximum_identifier"
    assert normalizer.field_name_mapping[long_name_77] == expected_77
    assert len(normalizer.field_name_mapping[long_name_77]) == 63

    # 78 characters - should be truncated to 63
    long_name_78 = (
        "this_is_a_really_long_field_name_with_many_words_that_exceeds_the_limit_of_63"
    )
    truncated_78 = normalizer.field_name_mapping[long_name_78]
    assert len(truncated_78) == 63
    assert truncated_78 == long_name_78[:63]  # Should be first 63 chars

    # 100 characters - should be truncated to 63
    assert normalizer.field_name_mapping["x" * 100] == "x" * 63
    assert len(normalizer.field_name_mapping["x" * 100]) == 63

    # 120 characters - should be truncated to 63
    long_name_120 = "field_" * 20
    truncated_120 = normalizer.field_name_mapping[long_name_120]
    assert len(truncated_120) == 63
    assert truncated_120 == long_name_120[:63]  # Should be first 63 chars


def test_length_truncation_with_duplicates(create_mock_layer):
    """Test length truncation with duplicate handling"""
    # Test when truncated names become duplicates
    layer = create_mock_layer(
        [
            "a" * 70,  # Will be truncated to "aaa...aaa" (63 chars)
            "a" * 80,  # Will also be truncated to "aaa...aaa" (63 chars) - duplicate!
            "a" * 90,  # Another duplicate after truncation
            "very_long_field_name_that_will_be_truncated_to_exactly_63_characters_here",
            "very_long_field_name_that_will_be_truncated_to_exactly_63_characters_different",
        ]
    )
    normalizer = FieldNameNormalizer(layer)

    # First long name gets truncated to 63 chars
    assert normalizer.field_name_mapping["a" * 70] == "a" * 63

    # Second long name with same prefix gets truncated and numbered
    # Since "aaa...aaa" (63 chars) is taken, it becomes "aaa...aaa_1" but that's too long
    # So it should be truncated further to accommodate the suffix
    second_name = normalizer.field_name_mapping["a" * 80]
    assert second_name != "a" * 63  # Should be different
    assert len(second_name) <= 63  # Should not exceed limit
    assert second_name.endswith("_1")  # Should have suffix

    # Third duplicate
    third_name = normalizer.field_name_mapping["a" * 90]
    assert third_name != "a" * 63  # Should be different
    assert third_name != second_name  # Should be different from second
    assert len(third_name) <= 63  # Should not exceed limit
    assert third_name.endswith("_2")  # Should have suffix

    # Long names that become the same after truncation
    name1 = "very_long_field_name_that_will_be_truncated_to_exactly_63_characters_here"
    name2 = (
        "very_long_field_name_that_will_be_truncated_to_exactly_63_characters_different"
    )
    truncated1 = normalizer.field_name_mapping[name1]
    truncated2 = normalizer.field_name_mapping[name2]

    # Both should be truncated
    assert len(truncated1) == 63
    assert len(truncated2) <= 63

    # They should be different (second one gets a suffix)
    assert truncated1 != truncated2


def test_feedback_messages(create_mock_layer, mock_feedback):
    """Test feedback messages"""
    layer = create_mock_layer(
        ["防火準防火", "select", "id"], ["String", "String", "Integer64"]
    )

    FieldNameNormalizer(layer, mock_feedback)

    # Verify pushInfo was called
    mock_feedback.pushInfo.assert_called()
    mock_feedback.pushWarning.assert_called()

    # Verify normalization and skip messages were output
    info_calls = mock_feedback.pushInfo.call_args_list
    warning_calls = mock_feedback.pushWarning.call_args_list

    info_messages = [call[0][0] for call in info_calls]
    warning_messages = [call[0][0] for call in warning_calls]

    # Verify normalization messages
    assert any(
        "normalized for PostgreSQL compatibility" in msg for msg in info_messages
    )
    # Verify skip messages
    assert any(
        "skipped due to unsupported data types" in msg for msg in warning_messages
    )


# Additional edge cases
def test_empty_field_name(create_mock_layer):
    """Test empty field name handling"""
    # Note: None causes AttributeError, so we test only strings
    layer = create_mock_layer(["", "  ", "   "])
    normalizer = FieldNameNormalizer(layer)

    # Empty string becomes field_1
    assert normalizer.field_name_mapping[""] == "field_1"
    # Spaces only become underscore (after stripping)
    assert normalizer.field_name_mapping["  "] == "_"
    assert normalizer.field_name_mapping["   "] == "__1"  # Duplicate of _


def test_special_postgresql_characters(create_mock_layer):
    """Test special PostgreSQL characters"""
    layer = create_mock_layer(
        [
            "field$name",
            "field@name",
            "field#name",
            "field%name",
            "field^name",
            "field&name",
            "field*name",
            "field(name)",
            "field[name]",
            "field{name}",
        ]
    )
    normalizer = FieldNameNormalizer(layer)

    # Special characters handling:
    # Some are removed, some are replaced with underscore
    assert normalizer.field_name_mapping["field$name"] == "fieldname"
    assert normalizer.field_name_mapping["field@name"] == "fieldname_1"
    assert normalizer.field_name_mapping["field#name"] == "fieldname_2"
    assert normalizer.field_name_mapping["field%name"] == "fieldname_3"
    assert normalizer.field_name_mapping["field^name"] == "fieldname_4"
    assert normalizer.field_name_mapping["field&name"] == "fieldname_5"
    assert normalizer.field_name_mapping["field*name"] == "fieldname_6"
    # Parentheses, brackets, and braces are replaced with underscores
    assert normalizer.field_name_mapping["field(name)"] == "field_name_"
    assert normalizer.field_name_mapping["field[name]"] == "field_name__1"
    assert normalizer.field_name_mapping["field{name}"] == "field_name__2"


def test_unicode_normalization(create_mock_layer):
    """Test various unicode characters"""
    layer = create_mock_layer(
        [
            "café",
            "naïve",
            "Zürich",
            "北京",
            "서울",
            "Москва",
            "القاهرة",
            "กรุงเทพ",
        ]
    )
    normalizer = FieldNameNormalizer(layer)

    # Non-ASCII characters should be removed
    assert normalizer.field_name_mapping["café"] == "caf"
    assert normalizer.field_name_mapping["naïve"] == "nave"
    assert normalizer.field_name_mapping["Zürich"] == "zrich"
    # Asian/Arabic characters become field_N
    assert normalizer.field_name_mapping["北京"] == "field_1"
    assert normalizer.field_name_mapping["서울"] == "field_2"
    assert normalizer.field_name_mapping["Москва"] == "field_3"
    assert normalizer.field_name_mapping["القاهرة"] == "field_4"
    assert normalizer.field_name_mapping["กรุงเทพ"] == "field_5"
