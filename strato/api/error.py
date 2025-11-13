from qgis.PyQt.QtCore import QCoreApplication


def _tr(message: str) -> str:
    """Translate API error strings lazily via Qt."""

    return QCoreApplication.translate("StratoApiError", message)


class AppError(Exception):
    """Custom exception for API errors"""

    def __init__(self, message: str, error: str = ""):
        self.message = message
        self.error = error
        super().__init__(message)


class ValidateError(Exception):
    """Exception for validation errors"""

    def __init__(self, message: str, error: str = ""):
        self.message = message
        self.error = error
        super().__init__(message)


class NotFoundError(Exception):
    """Exception for not found errors"""

    def __init__(self, message: str, error: str = ""):
        self.message = message
        self.error = error
        super().__init__(message)


class UnauthorizedError(Exception):
    """Exception for unauthorized errors"""

    def __init__(self, message: str, error: str = ""):
        self.message = message
        self.error = error
        super().__init__(message)


class QuotaExceededError(Exception):
    """Exception for quota exceeded errors"""

    def __init__(self, message: str, error: str = ""):
        self.message = message
        self.error = error
        super().__init__(message)


class ConflictError(Exception):
    """Exception for conflict errors"""

    def __init__(self, message: str, error: str = ""):
        self.message = message
        self.error = error
        super().__init__(message)


class UserFacingApiError(Exception):
    """API errors that should be surfaced to end users."""

    def __init__(self, message: str, error: str = "", user_message: str = ""):
        self.message = message
        self.error = error
        self.user_message = user_message or message
        super().__init__(message)


class UnderMaintenanceError(UserFacingApiError):
    """Exception for under maintenance errors"""

    def __init__(self, message: str, error: str = ""):
        super().__init__(
            message,
            error,
            _tr(
                "STRATO is currently undergoing maintenance. Please try again in a few minutes."
            ),
        )


def raise_error(error: dict):
    """
    APIのエラーレスポンスを受け取り、適切な例外を発生させる

    Args:
        error (dict): {"message": str, "error": str}

    Raises:
        AppError: _description_
        ValidateError: _description_
        NotFoundError: _description_
        UnauthorizedError: _description_
        QuotaExceededError: _description_
        ConflictError: _description_
        UnderMaintenanceError: _description_
        Exception: _description_
    """

    message = error.get("message", "")

    if message == "Application Error":
        raise AppError(message, error.get("error", ""))
    elif message == "Validation Error":
        raise ValidateError(message, error.get("error", ""))
    elif message == "Not Found":
        raise NotFoundError(message, error.get("error", ""))
    elif message == "Unauthorized":
        raise UnauthorizedError(message, error.get("error", ""))
    elif message == "Quota Exceeded":
        raise QuotaExceededError(message, error.get("error", ""))
    elif message == "Conflict":
        raise ConflictError(message, error.get("error", ""))
    elif message == "Under Maintenance":
        raise UnderMaintenanceError(message, error.get("error", ""))
    else:
        raise Exception(error)
