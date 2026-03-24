import pytest


@pytest.mark.usefixtures("qgis_plugin_path")
class TestRaiseError:
    """raise_error が message に応じて正しい例外を発生させることを検証する"""

    def _mod(self):
        from plugin_dir.kumoy.api import error

        return error

    def test_application_error(self):
        m = self._mod()
        with pytest.raises(m.AppError) as exc_info:
            m.raise_error({"message": "Application Error", "error": "detail"})
        assert exc_info.value.message == "Application Error"
        assert exc_info.value.error == "detail"

    def test_validation_error(self):
        m = self._mod()
        with pytest.raises(m.ValidateError) as exc_info:
            m.raise_error({"message": "Validation Error", "error": "bad field"})
        assert exc_info.value.message == "Validation Error"
        assert exc_info.value.error == "bad field"

    def test_not_found_error(self):
        m = self._mod()
        with pytest.raises(m.NotFoundError):
            m.raise_error({"message": "Not Found", "error": "resource missing"})

    def test_unauthorized_error(self):
        m = self._mod()
        with pytest.raises(m.UnauthorizedError):
            m.raise_error({"message": "Unauthorized", "error": "no token"})

    def test_quota_exceeded_error(self):
        m = self._mod()
        with pytest.raises(m.QuotaExceededError):
            m.raise_error({"message": "Quota exceeded", "error": "over limit"})

    def test_conflict_error(self):
        m = self._mod()
        with pytest.raises(m.ConflictError):
            m.raise_error({"message": "Conflict", "error": "already exists"})

    def test_under_maintenance_error(self):
        m = self._mod()
        with pytest.raises(m.UnderMaintenanceError):
            m.raise_error({"message": "Under Maintenance", "error": "try later"})

    def test_unknown_message_raises_generic_exception(self):
        m = self._mod()
        with pytest.raises(Exception, match="Something Else"):
            m.raise_error({"message": "Something Else", "error": "info"})

    def test_empty_message_raises_exception_with_dict(self):
        m = self._mod()
        with pytest.raises(Exception, match="only error"):
            m.raise_error({"error": "only error"})

    def test_missing_error_field_defaults_to_empty(self):
        m = self._mod()
        with pytest.raises(m.AppError) as exc_info:
            m.raise_error({"message": "Application Error"})
        assert exc_info.value.error == ""


@pytest.mark.usefixtures("qgis_plugin_path")
class TestFormatApiError:
    """format_api_error が各例外型から読みやすい文字列を返すことを検証する"""

    def _mod(self):
        from plugin_dir.kumoy.api import error

        return error

    def test_format_custom_error_with_both_fields(self):
        m = self._mod()
        err = m.AppError("Application Error", "something broke")
        assert m.format_api_error(err) == "Application Error - something broke"

    def test_format_custom_error_message_only(self):
        m = self._mod()
        err = m.NotFoundError("Not Found", "")
        assert m.format_api_error(err) == "Not Found"

    def test_format_generic_exception(self):
        m = self._mod()
        err = RuntimeError("boom")
        assert m.format_api_error(err) == "boom"

    def test_deduplicates_message_and_error(self):
        """message と error が同じ場合は重複しないこと"""
        m = self._mod()
        err = m.AppError("same", "same")
        assert m.format_api_error(err) == "same"
