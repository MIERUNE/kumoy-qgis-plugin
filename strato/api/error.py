class AppError(Exception):
    """Custom exception for API errors"""

    def __init__(self, message: str, error: str = ""):
        self.message = message
        self.error = error
        super().__init__(f"{message} : {error}")


class ValidateError(Exception):
    """Exception for validation errors"""

    def __init__(self, message: str, error: str = ""):
        self.message = message
        self.error = error
        super().__init__(f"{message} : {error}")


class NotFoundError(Exception):
    """Exception for not found errors"""

    def __init__(self, message: str, error: str = ""):
        self.message = message
        self.error = error
        super().__init__(f"{message} : {error}")


class UnauthorizedError(Exception):
    """Exception for unauthorized errors"""

    def __init__(self, message: str, error: str = ""):
        self.message = message
        self.error = error
        super().__init__(f"{message} : {error}")


class QuotaExceededError(Exception):
    """Exception for quota exceeded errors"""

    def __init__(self, message: str, error: str = ""):
        self.message = message
        self.error = error
        super().__init__(f"{message} : {error}")


class ConflictError(Exception):
    """Exception for conflict errors"""

    def __init__(self, message: str, error: str = ""):
        self.message = message
        self.error = error
        super().__init__(f"{message} : {error}")


class UnderMaintenanceError(Exception):
    """Exception for under maintenance errors"""

    def __init__(self, message: str, error: str = ""):
        self.message = message
        self.error = error
        super().__init__(message)


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
    elif message == "Quota exceeded":
        raise QuotaExceededError(message, error.get("error", ""))
    elif message == "Conflict":
        raise ConflictError(message, error.get("error", ""))
    elif message == "Under Maintenance":
        raise UnderMaintenanceError(message, error.get("error", ""))
    else:
        raise Exception(error)


def format_api_error(exception: Exception) -> str:
    """Return a readable string that prefers custom API error details."""

    parts = []

    message = getattr(exception, "message", None)
    if message:
        parts.append(str(message))

    detail = getattr(exception, "error", None)
    if detail:
        detail_str = str(detail)
        if detail_str not in parts:
            parts.append(detail_str)

    if parts:
        return " - ".join(parts)

    return str(exception)
