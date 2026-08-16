"""Graph failures sorted by remedy.

The SDK reports all failures as APIError with a status code. This module categorizes them once so
each caller does not re-derive remedies:

- GraphThrottled (429): Retriable. Graph supplies Retry-After.
- GraphForbidden (401/403): Token lacks permission.
- GraphNotFound (404): Resource not found or not visible.
- GraphUnavailable (5xx or no response): Service down or unreachable.

Anything else (400, 409) raises GraphFailure. Other status codes do not suggest remedies.

GraphPagingUnending is not a failed request—it is Graph answering 200 with empty pages while
advertising more. No status code describes it. Only the pagination walk sees it. It belongs here
because it is what Graph did wrong, and because being a GraphFailure carries it through
`shared/seam.py` as advice rather than crash.
"""

from collections.abc import Generator
from contextlib import contextmanager

import httpx
from kiota_abstractions.api_error import APIError
from msgraph.generated.models.o_data_errors.o_data_error import ODataError


class GraphFailure(Exception):
    """Graph request failure. Subclass indicates remedy. Support needs request_id."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None,
        code: str | None,
        request_id: str | None,
    ) -> None:
        super().__init__(message)
        self.status: int | None = status
        self.code: str | None = code
        self.request_id: str | None = request_id


class GraphThrottled(GraphFailure):
    """Rate limit from Graph. SDK retries did not outlast it. Obey Retry-After header for fastest
    recovery. None means Graph sent no header—choose your own backoff."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None,
        code: str | None,
        request_id: str | None,
        retry_after_seconds: float | None,
    ) -> None:
        super().__init__(message, status=status, code=code, request_id=request_id)
        self.retry_after_seconds: float | None = retry_after_seconds


class GraphForbidden(GraphFailure):
    """Graph refused the caller, not the request. TRAP: 401 (token rejected) and 403 (no scope)
    are both forbidden. Status tells them apart. 401 means sign in again. 403 means ask an
    administrator."""


class GraphNotFound(GraphFailure):
    """TRAP: Graph returns 404 for both not-found and not-visible. Cannot prove absence."""


class GraphUnavailable(GraphFailure):
    """Graph returned 5xx, timeout, or connection failure. Usually transient. TRAP: Some 500s are
    permanent for certain content (Loop components, certain cards). Endless retries spin."""


class GraphPagingUnending(GraphFailure):
    """Graph would not end a collection: a run of empty pages, every one advertising more.

    Not a failed request—each of those pages was a 200—so it carries no status, no code and no
    request id, and `_classify` never produces it. `pagination.collect_pages` raises it directly
    when the run exceeds `pagination.MAX_EMPTY_PAGES`, and `empty_pages` is how long that run was.

    A raise rather than the `assert` this used to be, for two reasons that are both about the bound
    being real. `python -O` strips asserts, and the bound is the only thing between a collection
    that answers nothing but empty pages and a walk that follows them until throttling or a timeout
    ends it—the thousand-page walk `MAX_EMPTY_PAGES` exists to prevent. And Graph misbehaving is
    the boundary this module exists to describe, not an invariant of this connector's own code.
    """

    def __init__(self, message: str, *, empty_pages: int) -> None:
        super().__init__(message, status=None, code=None, request_id=None)
        self.empty_pages: int = empty_pages


@contextmanager
def graph_errors() -> Generator[None]:
    """Translate SDK failures into Graph error types."""
    try:
        yield
    except APIError as error:
        raise _classify(error) from error
    except httpx.TransportError as error:
        raise GraphUnavailable(
            f"Could not reach Microsoft Graph: {error}",
            status=None,
            code=None,
            request_id=None,
        ) from error


def _classify(error: APIError) -> GraphFailure:
    status = error.response_status_code
    headers = _lowercase_headers(error)
    code = error.error.code if isinstance(error, ODataError) and error.error else None
    request_id = headers.get("request-id")
    message = f"Microsoft Graph returned {status}" + (f" ({code})" if code else "")

    if status == 429:
        return GraphThrottled(
            message,
            status=status,
            code=code,
            request_id=request_id,
            retry_after_seconds=_retry_after_seconds(headers),
        )
    if status in (401, 403):
        return GraphForbidden(message, status=status, code=code, request_id=request_id)
    if status == 404:
        return GraphNotFound(message, status=status, code=code, request_id=request_id)
    if status is not None and status >= 500:
        return GraphUnavailable(message, status=status, code=code, request_id=request_id)
    return GraphFailure(message, status=status, code=code, request_id=request_id)


def _lowercase_headers(error: APIError) -> dict[str, str]:
    """Convert response_headers to dict with lowercased keys."""
    return {name.lower(): value for name, value in (error.response_headers or {}).items()}


def _retry_after_seconds(headers: dict[str, str]) -> float | None:
    """Parse Retry-After header as delay-seconds or None."""
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
