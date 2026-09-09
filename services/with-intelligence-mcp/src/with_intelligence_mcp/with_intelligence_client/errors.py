"""One exception per outcome a caller has to tell apart.

`NotEntitled` exists because 403 is a documented answer on every path: the account is not
licensed for what was asked. A tool must report that rather than return a thin answer, since
"not licensed" and "nothing there" otherwise look identical.
"""


class WithIntelligenceError(Exception):
    """Base for everything this transport raises."""


class ApiError(WithIntelligenceError):
    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code: int = status_code


class AuthError(ApiError):
    """401 — the access token is missing, expired or rejected."""

    def __init__(self, message: str = "With Intelligence rejected the access token") -> None:
        super().__init__(message, status_code=401)


class NotEntitled(ApiError):
    """403 — reached the API, but this account is not licensed for it."""

    def __init__(self, message: str, *, path: str) -> None:
        super().__init__(message, status_code=403)
        self.path: str = path


class NotFound(ApiError):
    def __init__(self, message: str, *, path: str) -> None:
        super().__init__(message, status_code=404)
        self.path: str = path


class RateLimited(ApiError):
    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message, status_code=429)
        self.retry_after_seconds: float | None = retry_after_seconds


class Unreachable(WithIntelligenceError):
    """Network failure or a 5xx — not the same thing as being refused."""


class SignInFailed(WithIntelligenceError):
    """`/v3/auth/sign-in` refused the username and password."""
