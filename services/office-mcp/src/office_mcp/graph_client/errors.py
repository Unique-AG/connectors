"""Graph failures categorized by remedy, not just status code.

The SDK reports all failures as APIError, carrying status as data. Without categorizing, each
caller must re-derive remedies from the status code. This module draws distinctions once:

- GraphThrottled (429): retriable, Graph supplies Retry-After.
- GraphForbidden (401/403): token lacks permission.
- GraphNotFound (404): resource not found.
- GraphUnavailable (5xx or no response): service down or unreachable.

Anything else (400, 409) raises base GraphFailure. Inventing categories per status code would
guess at remedies that do not exist.
"""

from collections.abc import Generator
from contextlib import contextmanager

import httpx
from kiota_abstractions.api_error import APIError
from msgraph.generated.models.o_data_errors.o_data_error import ODataError


class GraphFailure(Exception):
    """Microsoft Graph request failure with status, code, and request ID.

    The subclass indicates the remedy; status/code/request_id provide evidence. 401 and 403 are
    both GraphForbidden, but only 401 is fixed by signing in again. Microsoft support needs
    request_id.
    """

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
    """Rate limit from Graph; SDK retries did not outlast it.

    `retry_after_seconds` is Graph's Retry-After header. Graph documents that obeying it is the
    fastest recovery path. Usage accrues while throttled, so eager retries make recovery worse.
    None means Graph sent no header; the caller must choose its own backoff.

    Reaching this means the request was retried GraphSettings.max_retries times or Retry-After
    exceeded the SDK's 180 s ceiling and the SDK declined to wait.
    """

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
    """Graph refused the caller, not the request.

    Covers 403 (token valid but no scope for this resource; usually missing admin consent) and
    401 (token rejected). Both are non-retriable and cannot be worked around by asking
    differently. Status separates them: tell user to sign in again (401) or ask an administrator
    (403).
    """


class GraphNotFound(GraphFailure):
    """Resource not found or not visible to caller.

    TRAP: Graph returns 404 for both. This cannot prove absence.
    """


class GraphUnavailable(GraphFailure):
    """Graph returned 5xx, timeout, or connection failure.

    Usually transient. TRAP: teams-mcp found recurring 500s on every attempt when a chat contains
    Loop components or certain cards that Graph cannot serialize. Callers that retry forever spin.
    """


@contextmanager
def graph_errors() -> Generator[None]:
    """Translate SDK failures into the four Graph error types for one block of calls.

    Wrap a tool's entire Graph work in one with statement, not each call. Classification is the
    same everywhere; copying try/except into every tool wastes code.
    """
    try:
        yield
    except APIError as error:
        raise _classify(error) from error
    except httpx.TransportError as error:
        # No HTTP response at all: DNS, connect, read timeout. Never reaches `APIError`, which
        # the request adapter only raises once a response exists.
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
    """Convert APIError.response_headers to a plain dict with lowercased keys.

    The attribute type is dict[str, str], but the request adapter may assign httpx.Headers
    (case-insensitive). Lowercase keys work for both.
    """
    return {name.lower(): value for name, value in (error.response_headers or {}).items()}


def _retry_after_seconds(headers: dict[str, str]) -> float | None:
    """Parse Retry-After header as delay-seconds if Graph sent a number.

    Graph documents the header as delay-seconds. The HTTP-date form is legal but never observed
    here. Guessing wrong about the caller's clock is worse than reporting nothing. None already
    means "no advice from Graph".
    """
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
