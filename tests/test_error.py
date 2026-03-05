import importlib.util
import unittest
from pathlib import Path

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


class TestRaiseError(unittest.TestCase):
    """raise_error が message に応じて正しい例外を発生させることを検証する"""

    def test_application_error(self):
        with self.assertRaises(AppError) as ctx:
            raise_error({"message": "Application Error", "error": "detail"})
        self.assertEqual(ctx.exception.message, "Application Error")
        self.assertEqual(ctx.exception.error, "detail")

    def test_validation_error(self):
        with self.assertRaises(ValidateError) as ctx:
            raise_error({"message": "Validation Error", "error": "bad field"})
        self.assertEqual(ctx.exception.message, "Validation Error")
        self.assertEqual(ctx.exception.error, "bad field")

    def test_not_found_error(self):
        with self.assertRaises(NotFoundError):
            raise_error({"message": "Not Found", "error": "resource missing"})

    def test_unauthorized_error(self):
        with self.assertRaises(UnauthorizedError):
            raise_error({"message": "Unauthorized", "error": "no token"})

    def test_quota_exceeded_error(self):
        with self.assertRaises(QuotaExceededError):
            raise_error({"message": "Quota exceeded", "error": "over limit"})

    def test_conflict_error(self):
        with self.assertRaises(ConflictError):
            raise_error({"message": "Conflict", "error": "already exists"})

    def test_under_maintenance_error(self):
        with self.assertRaises(UnderMaintenanceError):
            raise_error({"message": "Under Maintenance", "error": "try later"})

    def test_unknown_message_raises_generic_exception(self):
        with self.assertRaises(Exception) as ctx:
            raise_error({"message": "Something Else", "error": "info"})
        self.assertIn("Something Else", str(ctx.exception))

    def test_empty_message_raises_exception_with_dict(self):
        payload = {"error": "only error"}
        with self.assertRaises(Exception) as ctx:
            raise_error(payload)
        self.assertIn("only error", str(ctx.exception))

    def test_missing_error_field_defaults_to_empty(self):
        with self.assertRaises(AppError) as ctx:
            raise_error({"message": "Application Error"})
        self.assertEqual(ctx.exception.error, "")


class TestFormatApiError(unittest.TestCase):
    """format_api_error が各例外型から読みやすい文字列を返すことを検証する"""

    def test_format_custom_error_with_both_fields(self):
        err = AppError("Application Error", "something broke")
        result = format_api_error(err)
        self.assertEqual(result, "Application Error - something broke")

    def test_format_custom_error_message_only(self):
        err = NotFoundError("Not Found", "")
        result = format_api_error(err)
        self.assertEqual(result, "Not Found")

    def test_format_generic_exception(self):
        err = RuntimeError("boom")
        result = format_api_error(err)
        self.assertEqual(result, "boom")

    def test_deduplicates_message_and_error(self):
        """message と error が同じ場合は重複しないこと"""
        err = AppError("same", "same")
        result = format_api_error(err)
        self.assertEqual(result, "same")


if __name__ == "__main__":
    unittest.main()
