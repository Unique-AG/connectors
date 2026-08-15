"""Graph failures sorted by remedy.

The SDK reports all failures as APIError with a status code. This module categorizes them once so
each caller does not re-derive remedies:

- GraphThrottled (429): Retriable. Graph supplies Retry-After.
- GraphForbidden (401/403): Token lacks permission.
- GraphNotFound (404): Resource not found or not visible.
- GraphUnavailable (5xx or no response): Service down or unreachable.

Anything else (400, 409) raises GraphFailure. Other status codes do not suggest remedies.

One of them is not a failed request at all. `GraphPagingUnending` is Graph answering 200 after 200
with nothing in them while still advertising more of a collection, which no status code describes
and the SDK therefore cannot report — only the walk in `pagination` sees it. It belongs here
anyway, because "what Graph did wrong" is what this vocabulary is and because being a
`GraphFailure` is what carries it through `shared/seam.py` to the caller as advice rather than as a
crash.

One thing above the status code is carried too: `inner_code`, Graph's `error.innerError.code`.
Where a status and an outer code are the same for two failures with opposite remedies, that is
the only field that tells them apart — the transcript APIs answer both "your tenant has switched
Graph access to transcripts off, and no app can switch it back on" and "this tenant will not give
you speaker names, ask for the unattributed format" as `403 Forbidden` / `code: Forbidden`, and
Microsoft's own instruction is to "branch on the `innerError.code` value, not the message text.
Messages are subject to change" (https://learn.microsoft.com/en-us/graph/api/calltranscript-get).
It is data like `status` is, not a category: a subclass per inner code would be a subclass per
Graph feature.

`graph_errors` also counts and times the call it wraps. It is the seam every Graph call already
goes through, and the categories above are exactly the `status` a counter wants — measuring
anywhere else would mean re-deriving them. The instruments themselves live in
`graph_client/observability.py`; this module supplies the taxonomy and nothing else about them.
"""

from collections.abc import Generator
from contextlib import contextmanager
from time import perf_counter
from typing import cast

import httpx
from kiota_abstractions.api_error import APIError
from kiota_http.middleware.options.retry_handler_option import RetryHandlerOption
from msgraph.generated.models.o_data_errors.o_data_error import ODataError

from office_mcp.graph_client.observability import (
    graph_operation,
    record_graph_call,
    record_graph_throttled,
)


class GraphFailure(Exception):
    """Graph request failure. Subclass indicates remedy. Support needs request_id.

    `inner_code` defaults to `None` because most Graph errors carry no
    inner code worth branching on; where one does, it is the whole of the difference.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None,
        code: str | None,
        request_id: str | None,
        inner_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status: int | None = status
        self.code: str | None = code
        self.request_id: str | None = request_id
        self.inner_code: str | None = inner_code


class GraphThrottled(GraphFailure):
    """Rate limit from Graph. SDK retries did not outlast it. Obey Retry-After header for fastest
    recovery: usage keeps accruing while throttled, so an early retry only extends the wait. This
    means the SDK already retried `GraphSettings.max_retries` times, or Retry-After asked for more
    than the SDK's 180 s wait ceiling and it gave up. None means Graph sent no header—choose your
    own backoff."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None,
        code: str | None,
        request_id: str | None,
        retry_after_seconds: float | None,
        inner_code: str | None = None,
    ) -> None:
        super().__init__(
            message, status=status, code=code, request_id=request_id, inner_code=inner_code
        )
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


# The `status` label each failure is counted under. Named per class rather than derived from the
# HTTP code, because the code is the thing this module exists to stop callers reading: 401 and 403
# are one remedy, 500 and 503 are another, and a counter keyed on the code would have a series per
# thing Graph can answer.
_STATUS: dict[type[GraphFailure], str] = {
    GraphThrottled: "throttled",
    GraphForbidden: "forbidden",
    GraphNotFound: "not_found",
    GraphUnavailable: "unavailable",
    GraphPagingUnending: "paging_unending",
    GraphFailure: "failed",
}

_OK = "ok"

# What a call is counted as when something left this block that is not a Graph failure at all — an
# `assert` in the caller's own code, a cancellation. Not "failed": a Graph status must mean Graph
# said something.
_UNCLASSIFIED = "error"


@contextmanager
def graph_errors(operation: str | None = None) -> Generator[None]:
    """Translate SDK failures into Graph error types, and count what the call cost.

    `operation` is the name this call is counted under — pass the tool's own `TOOL_NAME`. It must be
    a name chosen in code and never anything off the URL; see `observability.py` for why that is a
    hard rule rather than a preference. Left out, the call is not measured at all, which is what a
    test driving the SDK directly wants and is a defect in a tool: the tool is then missing from
    every Graph dashboard rather than showing up under a wrong name.
    """
    started = perf_counter()
    # Pessimistic on purpose: every path below replaces it, so this value surviving means an
    # exception escaped that this seam does not know how to describe.
    status = _UNCLASSIFIED
    try:
        with graph_operation(operation):
            yield
        status = _OK
    except APIError as error:
        failure = _classify(error)
        status = _status_of(failure)
        if isinstance(failure, GraphThrottled):
            record_graph_throttled(operation, retried=_sdk_spent_its_retries(failure))
        raise failure from error
    except httpx.TransportError as error:
        # DNS, connect, or read timeout: no HTTP response exists yet. The request adapter raises
        # `APIError` only once a response exists, so this failure never reaches that clause.
        status = _STATUS[GraphUnavailable]
        raise GraphUnavailable(
            f"Could not reach Microsoft Graph: {error}",
            status=None,
            code=None,
            request_id=None,
        ) from error
    except GraphFailure as failure:
        # Raised inside the block rather than translated here: `collect_pages` refusing a collection
        # Graph will not end is the one that happens.
        status = _status_of(failure)
        raise
    finally:
        record_graph_call(operation, status=status, seconds=perf_counter() - started)


def _status_of(failure: GraphFailure) -> str:
    """The label for this failure. A subclass nobody has written yet counts as a plain failure."""
    return _STATUS.get(type(failure), _STATUS[GraphFailure])


def _sdk_spent_its_retries(failure: GraphThrottled) -> bool:
    """Whether the SDK retried this 429 before giving up on it.

    A 429 the SDK recovered from never reaches this module, so every throttling counted here is
    throttling that survived — and it survives in two ways with opposite remedies. The retry
    handler refuses to wait at all once the delay reaches its 180 s ceiling
    (`kiota_http/middleware/retry_handler.py:97`), so a `Retry-After` that long means no attempt was
    made and the answer is available later; anything shorter means `GraphSettings.max_retries`
    attempts were spent and the quota is genuinely gone.

    No header at all reads as retried, because that is what the SDK does with one: it falls back to
    exponential backoff, which is always under the ceiling.
    """
    advice = failure.retry_after_seconds
    return advice is None or advice < RetryHandlerOption.MAX_DELAY


def _classify(error: APIError) -> GraphFailure:
    status = error.response_status_code
    headers = _lowercase_headers(error)
    code = error.error.code if isinstance(error, ODataError) and error.error else None
    inner_code = _inner_code(error)
    request_id = headers.get("request-id")
    message = f"Microsoft Graph returned {status}" + (f" ({code})" if code else "")

    if status == 429:
        return GraphThrottled(
            message,
            status=status,
            code=code,
            request_id=request_id,
            inner_code=inner_code,
            retry_after_seconds=_retry_after_seconds(headers),
        )
    if status in (401, 403):
        return GraphForbidden(
            message, status=status, code=code, request_id=request_id, inner_code=inner_code
        )
    if status == 404:
        return GraphNotFound(
            message, status=status, code=code, request_id=request_id, inner_code=inner_code
        )
    if status is not None and status >= 500:
        return GraphUnavailable(
            message, status=status, code=code, request_id=request_id, inner_code=inner_code
        )
    return GraphFailure(
        message, status=status, code=code, request_id=request_id, inner_code=inner_code
    )


def _inner_code(error: APIError) -> str | None:
    """Graph's `error.innerError.code`, if it sent one.

    The SDK's generated `innerError` has typed fields for `request-id`, `client-request-id` and
    `date` and none for `code`, so the property Microsoft tells callers to branch on arrives in the
    model's `additional_data` — untyped by construction, hence the narrowing.
    """
    if not isinstance(error, ODataError) or error.error is None:
        return None
    inner = error.error.inner_error
    if inner is None:
        return None
    extra = cast("dict[str, object]", inner.additional_data)
    value = extra.get("code")
    return value if isinstance(value, str) else None


def _lowercase_headers(error: APIError) -> dict[str, str]:
    """Convert response_headers to dict with lowercased keys.

    The declared type is dict[str, str], but the request adapter may assign httpx.Headers
    instead. httpx.Headers is case-insensitive; lowercasing the keys makes both forms behave alike.
    """
    return {name.lower(): value for name, value in (error.response_headers or {}).items()}


def _retry_after_seconds(headers: dict[str, str]) -> float | None:
    """Parse Retry-After header as delay-seconds or None.

    Graph documents this header as delay-seconds and never sends the legal HTTP-date form here.
    This parser does not guess at that form: a wrong guess about the caller's clock is worse than
    reporting no advice.
    """
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
