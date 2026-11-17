"""Typed errors raised by the Kumoy API client.

The class is chosen from the HTTP status, not from the response text: the
backend's `message` strings are categories that may change, while the status
codes are its contract.
"""

from typing import Optional


class AppError(Exception):
    """Base class of every error the API client raises."""

    def __init__(self, message: str, error: str = "", status: Optional[int] = None):
        self.message = message
        self.error = error
        self.status = status
        super().__init__(f"{message} : {error}" if error else message)


class NetworkError(AppError):
    """No HTTP response: offline, DNS, TLS, proxy or timeout."""


class ValidateError(AppError):
    pass


class NotFoundError(AppError):
    pass


class UnauthorizedError(AppError):
    """401: the session is missing, expired or revoked. Log in again."""


class ForbiddenError(AppError):
    """403: logged in, but the role or plan does not allow this operation.

    Kept separate from UnauthorizedError so that a permission problem never
    logs the user out.
    """


class ConflictError(AppError):
    pass


class QuotaExceededError(AppError):
    """429 outside /api/auth: a plan limit (storage, counts) was reached."""


class UnderMaintenanceError(AppError):
    pass


_BY_STATUS = {
    401: UnauthorizedError,
    403: ForbiddenError,
    404: NotFoundError,
    409: ConflictError,
    422: ValidateError,
    429: QuotaExceededError,
    503: UnderMaintenanceError,
}


def error_from_response(status: Optional[int], body: object, fallback: str) -> AppError:
    """Build the error for a failed response.

    `body` is the decoded JSON, if any. The backend answers
    {"message", "error"}, but zod validation failures and better-auth use other
    shapes, so anything unexpected degrades to `fallback` instead of raising.
    """
    message, detail = "", ""
    if isinstance(body, dict):
        message = str(body.get("message") or "")
        raw = body.get("error")
        detail = raw if isinstance(raw, str) else ""
        if not detail:
            detail = str(body.get("error_description") or "")
    if status is None:
        return NetworkError(fallback, detail, status)
    cls = _BY_STATUS.get(status, AppError)
    return cls(message or fallback or f"HTTP {status}", detail, status)


def format_api_error(exception: Exception) -> str:
    """Return a readable one-line description of an exception."""
    if isinstance(exception, AppError):
        parts = [p for p in (exception.message, exception.error) if p]
        # Avoid "X - X" when the server repeats itself
        if len(parts) == 2 and parts[0] == parts[1]:
            parts = parts[:1]
        if parts:
            return " - ".join(parts)
    return str(exception)
