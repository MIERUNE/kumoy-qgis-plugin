import importlib.util
from pathlib import Path

import pytest

# Load error module without importing the heavy QGIS package tree.
MODULE_PATH = Path(__file__).resolve().parent.parent / "kumoy" / "api" / "error.py"
spec = importlib.util.spec_from_file_location("error_module", MODULE_PATH)
error_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(error_module)

raise_error = error_module.raise_error
format_api_error = error_module.format_api_error
AppError = error_module.AppError
ValidateError = error_module.ValidateError
NotFoundError = error_module.NotFoundError
UnauthorizedError = error_module.UnauthorizedError
QuotaExceededError = error_module.QuotaExceededError
ConflictError = error_module.ConflictError
UnderMaintenanceError = error_module.UnderMaintenanceError


class TestRaiseError:
    """raise_error が message に応じて正しい例外を発生させることを検証する"""

    def test_application_error(self):
        with pytest.raises(AppError) as exc_info:
            raise_error({"message": "Application Error", "error": "detail"})
        assert exc_info.value.message == "Application Error"
        assert exc_info.value.error == "detail"

    def test_validation_error(self):
        with pytest.raises(ValidateError) as exc_info:
            raise_error({"message": "Validation Error", "error": "bad field"})
        assert exc_info.value.message == "Validation Error"
        assert exc_info.value.error == "bad field"

    def test_not_found_error(self):
        with pytest.raises(NotFoundError):
            raise_error({"message": "Not Found", "error": "resource missing"})

    def test_unauthorized_error(self):
        with pytest.raises(UnauthorizedError):
            raise_error({"message": "Unauthorized", "error": "no token"})

    def test_quota_exceeded_error(self):
        with pytest.raises(QuotaExceededError):
            raise_error({"message": "Quota exceeded", "error": "over limit"})

    def test_conflict_error(self):
        with pytest.raises(ConflictError):
            raise_error({"message": "Conflict", "error": "already exists"})

    def test_under_maintenance_error(self):
        with pytest.raises(UnderMaintenanceError):
            raise_error({"message": "Under Maintenance", "error": "try later"})

    def test_unknown_message_raises_generic_exception(self):
        with pytest.raises(Exception, match="Something Else"):
            raise_error({"message": "Something Else", "error": "info"})

    def test_empty_message_raises_exception_with_dict(self):
        with pytest.raises(Exception, match="only error"):
            raise_error({"error": "only error"})

    def test_missing_error_field_defaults_to_empty(self):
        with pytest.raises(AppError) as exc_info:
            raise_error({"message": "Application Error"})
        assert exc_info.value.error == ""


class TestFormatApiError:
    """format_api_error が各例外型から読みやすい文字列を返すことを検証する"""

    def test_format_custom_error_with_both_fields(self):
        err = AppError("Application Error", "something broke")
        assert format_api_error(err) == "Application Error - something broke"

    def test_format_custom_error_message_only(self):
        err = NotFoundError("Not Found", "")
        assert format_api_error(err) == "Not Found"

    def test_format_generic_exception(self):
        err = RuntimeError("boom")
        assert format_api_error(err) == "boom"

    def test_deduplicates_message_and_error(self):
        """message と error が同じ場合は重複しないこと"""
        err = AppError("same", "same")
        assert format_api_error(err) == "same"
