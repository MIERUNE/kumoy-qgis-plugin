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


def handle_error(error: dict):
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
    else:
        raise Exception(message)
