from plugin_dir.processing.upload_vector.normalize_field_name import (
    normalize_field_name,
)


class TestNormalizeFieldName:
    def test_strips_leading_and_trailing_whitespace(self):
        assert normalize_field_name("  field_name  ", current_names=[]) == "field_name"

    def test_returns_original_when_unique(self):
        assert (
            normalize_field_name("Field Name", current_names=["Other"]) == "Field Name"
        )

    def test_adds_suffix_when_duplicate(self):
        assert normalize_field_name("field", current_names=["field"]) == "field_1"

    def test_trims_to_maximum_length(self):
        long_name = "a" * 80
        assert normalize_field_name(long_name, current_names=[]) == "a" * 63

    def test_suffix_increments_until_unique(self):
        current_names = ["field", "field_1", "field_2"]
        assert normalize_field_name("field", current_names=current_names) == "field_3"

    def test_suffix_reaches_two_digits(self):
        existing = ["field"] + [f"field_{i}" for i in range(1, 10)]
        assert normalize_field_name("field", current_names=existing) == "field_10"

    def test_suffix_respects_max_length(self):
        base = "a" * 63
        assert normalize_field_name(base, current_names=[base]) == "a" * 61 + "_1"

    def test_suffix_continues_after_truncated_match(self):
        base = "a" * 63
        current_names = [base, "a" * 61 + "_1"]
        assert (
            normalize_field_name(base, current_names=current_names) == "a" * 61 + "_2"
        )

    def test_suffix_truncates_again_when_length_grows(self):
        base = "a" * 63
        current_names = [base] + ["a" * 61 + f"_{i}" for i in range(1, 10)]
        assert (
            normalize_field_name(base, current_names=current_names) == "a" * 60 + "_10"
        )
