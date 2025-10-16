import importlib.util
import unittest
from pathlib import Path

# Load normalize_field_name without importing the heavy QGIS package tree.
MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "processing"
    / "upload_vector"
    / "normalize_field_name.py"
)
spec = importlib.util.spec_from_file_location(
    "normalize_field_name_module", MODULE_PATH
)
normalize_field_name_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(normalize_field_name_module)
normalize_field_name = normalize_field_name_module.normalize_field_name


class TestNormalizeFieldName(unittest.TestCase):
    def test_basic_transformation(self):
        result = normalize_field_name("Field Name", current_names=[])
        self.assertEqual(result, "field_name")

    def test_special_characters_become_underscores(self):
        result = normalize_field_name("My Field!", current_names=[])
        self.assertEqual(result, "my_field_")

    def test_reserved_keyword_gets_suffix(self):
        result = normalize_field_name("Select", current_names=[])
        self.assertEqual(result, "select_")

    def test_trims_to_maximum_length(self):
        long_name = "a" * 80
        result = normalize_field_name(long_name, current_names=[])
        self.assertEqual(result, "a" * 63)

    def test_leading_digits_removed(self):
        result = normalize_field_name("123_field", current_names=[])
        self.assertEqual(result, "_field")

    def test_fallback_when_name_becomes_empty(self):
        result = normalize_field_name("123", current_names=["field", "field_1"])
        self.assertEqual(result, "field_2")


if __name__ == "__main__":
    unittest.main()
