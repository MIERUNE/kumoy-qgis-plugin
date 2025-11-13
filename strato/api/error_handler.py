"""Utilities for surfacing STRATO API errors to the UI layers."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Optional, Type

from . import error as api_error

NotifyFn = Optional[Callable[[str], None]]


class UserFacingAbort(RuntimeError):
    """Raised to stop control flow after the user has been notified."""

    pass


def handle_user_facing_error(
    exc: api_error.UserFacingApiError,
    *,
    notify_user: NotifyFn = None,
    rethrow_as: Optional[Type[Exception]] = None,
):
    """Dispatch a user-facing API error to the caller's notification channel."""

    message = exc.user_message
    if notify_user:
        notify_user(message)

    if rethrow_as is not None:
        raise rethrow_as(message) from exc

    raise exc


@contextmanager
def api_guard(*, notify_user: NotifyFn = None, rethrow_as: Optional[Type[Exception]] = None):
    """Context manager to keep API try/except blocks minimal."""

    try:
        yield
    except api_error.UserFacingApiError as exc:  # pragma: no cover - thin wrapper
        handle_user_facing_error(
            exc,
            notify_user=notify_user,
            rethrow_as=rethrow_as,
        )
