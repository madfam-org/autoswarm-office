"""Exception classes for the Selva SDK."""


class SelvaError(Exception):
    """Base exception for Selva SDK."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AuthenticationError(SelvaError):
    """Raised when authentication fails (401/403)."""


class TaskTimeoutError(SelvaError):
    """Raised when wait_for_task exceeds timeout."""


class NotFoundError(SelvaError):
    """Raised when a resource is not found (404)."""
