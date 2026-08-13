"""The Graph failures a caller has to answer differently.

The SDK reports every failed request as one type — `kiota_abstractions.api_error.APIError` (or
its `ODataError` subclass when Graph sent a parseable error body) — carrying the HTTP status as
data. "Wait and try again", "you were never allowed to read this", "there is no such chat" and
"Microsoft is having an outage" therefore arrive indistinguishable unless each caller re-derives
the difference from a status code. Later pieces map an MCP error onto each of them, so the
distinctions are drawn once, here, and only the ones Graph actually makes:

* `GraphThrottled` — 429. Retriable, and Graph says when: `Retry-After`.
* `GraphForbidden` — 401/403. The caller's token does not permit this call.
* `GraphNotFound` — 404.
* `GraphUnavailable` — 5xx, or no response at all.

Anything else (a 400 from a malformed `$filter`, a 409) raises the base `GraphFailure`: it is a
Graph failure with a status and a code, and inventing a category per status code Graph might
return would be guessing at remedies that don't exist.
"""

from collections.abc import Generator
from contextlib import contextmanager

import httpx
from kiota_abstractions.api_error import APIError
from msgraph.generated.models.o_data_errors.o_data_error import ODataError


class GraphFailure(Exception):
    """A Microsoft Graph request that failed.

    `status` and `code` are carried even where the subclass implies them. The subclass is the
    remedy — what a caller does about it — while these are the evidence: 401 and 403 are both
    `GraphForbidden` but only one of them is fixed by signing in again, and `request_id` is what
    Microsoft support asks for.
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
    """Graph is rate-limiting us, and the SDK's retries did not outlast it.

    `retry_after_seconds` is Graph's own `Retry-After`, which its throttling documentation is
    explicit is the fastest way to recover — usage keeps accruing while a client is throttled,
    so an eager retry makes things worse. `None` means Graph sent no header, in which case the
    caller has nothing better than a backoff of its own.

    Reaching this at all means the request was already retried `GraphSettings.max_retries`
    times, or that `Retry-After` exceeded the SDK's 180 s ceiling and it declined to wait.
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

    Covers 403 (the token is valid but carries no scope for this resource — the usual shape of
    a missing admin consent, e.g. channel messages without `ChannelMessage.Read.All`) and 401
    (Graph rejected the token itself). Both are non-retriable and neither is something the
    caller can work around by asking differently; `status` separates them for a message that
    tells the user whether to sign in again or to ask an administrator.
    """


class GraphNotFound(GraphFailure):
    """No such resource — or none the caller is allowed to know exists.

    Graph returns 404 for both, deliberately, so this cannot be read as proof of absence.
    """


class GraphUnavailable(GraphFailure):
    """Graph erred or could not be reached: 5xx, a timeout, or a connection failure.

    Usually transient, but not always: teams-mcp found 500s that recur on every attempt when a
    chat contains content Graph itself cannot serialize (Loop components, some cards). A caller
    that retries this forever will spin on those.
    """


@contextmanager
def graph_errors() -> Generator[None]:
    """Translate the SDK's failures into the four above, for one block of Graph calls.

    Wrap the whole of a tool's Graph work in one `with`, rather than each call: the
    classification is the same everywhere, and the alternative is the same `try`/`except` copied
    into every tool.
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
    """`APIError.response_headers`, keyed for lookup.

    The attribute is annotated `dict[str, str]` but the request adapter assigns the response's
    `httpx.Headers` to it verbatim, which is case-insensitive. Lowercasing the keys here means
    the lookups below hold for whichever of the two it actually is.
    """
    return {name.lower(): value for name, value in (error.response_headers or {}).items()}


def _retry_after_seconds(headers: dict[str, str]) -> float | None:
    """`Retry-After` as a number of seconds, if Graph sent one that is a number of seconds.

    Graph documents the header as delay-seconds and that is what its throttling responses send.
    The HTTP-date form is legal but never observed here, and guessing wrong about the caller's
    clock is worse than reporting nothing: `None` already means "no advice from Graph".
    """
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
