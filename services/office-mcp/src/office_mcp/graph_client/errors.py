"""Graph failures sorted by remedy.

The SDK reports all failures as APIError with a status code. This module categorizes them once so
each caller does not re-derive remedies:

- GraphThrottled (429, or a retriable 5xx that named a delay): Retriable. Graph supplies
  Retry-After.
- GraphForbidden (401/403): Token lacks permission.
- GraphNotFound (404): Resource not found or not visible.
- GraphUnavailable (a 5xx with nothing to wait for, or no response): Service down or unreachable.

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

Two failures reach a caller that Graph never described at all, and both used to escape this module
entirely — unworded to the caller and counted under the `error` sentinel that means "an exception
this seam cannot describe". `KiotaHTTPXError` is the SDK's own family, and two of its members are
reachable from a Graph call: `RedirectError` when the redirect handler gives up
(`kiota_http/middleware/redirect_handler.py:94`) and `ResponseError` when the adapter gets no
response to read (`kiota_http/httpx_request_adapter.py:602`). Neither carries a status, a code or a
request id, and both mean the same thing to a caller, so both are `GraphUnavailable`. Caught as the
base class rather than as the two, because the family is what the SDK promises and a third member
becoming reachable should not need this line edited to stay classified.
`CancelledError` is the other, and it is not a failure of anything: the caller went away. It keeps
its own status so that an MCP client hanging up stops reading on a dashboard as this connector
failing, and it is re-raised untranslated so the task group that sent it learns it was obeyed.

`graph_errors` also counts and times the operation it wraps, and `graph_step` counts one Graph call
inside it. They are the seam every Graph call already goes through, and the categories above are
exactly the `status` a counter wants — measuring anywhere else would mean re-deriving them. The
instruments themselves live in `graph_client/observability.py`; this module supplies the taxonomy
and nothing else about them.
"""

from asyncio import CancelledError
from collections.abc import Generator
from contextlib import contextmanager
from time import perf_counter
from typing import cast

import httpx
from kiota_abstractions.api_error import APIError
from kiota_http._exceptions import KiotaHTTPXError
from kiota_http.middleware.options.retry_handler_option import RetryHandlerOption
from kiota_http.middleware.retry_handler import RetryHandler
from msgraph.generated.models.o_data_errors.o_data_error import ODataError

from office_mcp.graph_client.observability import (
    current_graph_operation,
    graph_operation,
    record_graph_call,
    record_graph_step,
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
    own backoff.

    TRAP: this is not only 429. Graph also holds a caller off with a 5xx that carries Retry-After,
    and `status` is what tells the two apart where that matters — a 429 is quota, a 503 with a
    delay may be quota or load shedding. Either way the delay is the remedy, which is why they are
    one class; see `_is_throttling`."""

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
    """Graph returned a 5xx with nothing to wait for, timed out, or could not be reached. Usually
    transient. TRAP: Some 500s are permanent for certain content (Loop components, certain cards).
    Endless retries spin. A 5xx that did name a delay is `GraphThrottled`, not this: the remedy
    there is the delay, and counting it here would read on a dashboard as an outage."""


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
# are one remedy, a 500 and a 503 nobody was asked to wait for are another, and a counter keyed on
# the code would have a series per thing Graph can answer.
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
# `assert` in the caller's own code, a bug in a tool body. Not "failed": a Graph status must mean
# Graph said something.
_UNCLASSIFIED = "error"

# The caller went away — an MCP client disconnected, or the request task was cancelled — while a
# Graph call was in flight. Its own label rather than `_UNCLASSIFIED`, because cancellation is the
# one non-Graph exception that happens routinely in production, and counted as `error` it reads on
# a dashboard as this connector failing.
_CANCELLED = "cancelled"

# Every value the `status` label can take, so that the bound is a thing a reader can see and a test
# can assert rather than a claim. Public because a dashboard has to decide, for each one, whether it
# counts as a failure — `cancelled` is the one that answers differently from every other non-`ok`
# value, and the way that decision gets forgotten is nobody being able to enumerate the options.
GRAPH_STATUSES: frozenset[str] = frozenset({*_STATUS.values(), _OK, _UNCLASSIFIED, _CANCELLED})


@contextmanager
def graph_errors(operation: str, *, step: str | None = None) -> Generator[None]:
    """Translate SDK failures into Graph error types, and count what the operation cost.

    `operation` is the name this call is counted under — pass the tool's own `TOOL_NAME`. It must be
    a name chosen in code and never anything off the URL; see `observability.py` for why that is a
    hard rule rather than a preference. It is required: a tool that could leave it out would be
    missing from every Graph dashboard, and nothing at the call site would say so. A test driving
    the SDK directly names itself like anything else does.

    `step` names one Graph call inside this block for the finer-grained instruments, for the tool
    that makes exactly one. A tool that makes several uses `graph_step` around each instead.
    """
    with _measured(operation, step=step):
        yield


@contextmanager
def graph_step(step: str) -> Generator[None]:
    """Measure one Graph call inside the `graph_errors` block already in scope.

    This is what restores per-call visibility inside a tool that makes several Graph calls: the
    operation-level instruments still answer "what did this tool call cost", and the step-level ones
    answer "which Graph call inside it was slow". The operation comes from the block above rather
    than from an argument, because it is already in scope and a second argument would be a second
    thing to keep in agreement with the first.

    Outside any `graph_errors` block there is no operation to attribute a step to, so nothing is
    recorded — the same rule `record_graph_call` keeps, and for the same reason.
    """
    with _measured(current_graph_operation(), step=step, operation_level=False):
        yield


@contextmanager
def _measured(
    operation: str | None, *, step: str | None, operation_level: bool = True
) -> Generator[None]:
    """The one translation-and-measurement block both entry points above are.

    `operation_level` is False for a step inside an operation: the outer block is already timing and
    counting the whole thing, and counting it twice would make `graph_operations_total` a count of
    blocks entered rather than of operations served.
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
    except CancelledError:
        # Not a failure of anything, and deliberately re-raised untranslated: cancellation has to
        # keep propagating as itself or the task group that sent it never learns it was obeyed.
        status = _CANCELLED
        raise
    except KiotaHTTPXError as error:
        # The SDK's own failures that are not `APIError`: too many redirects (`RedirectError`) and
        # no response to read (`ResponseError`) are the two reachable from a Graph call. Both are
        # raised outside the request/response cycle `_classify` describes, so neither carries a
        # status, a code or a request id — and without this clause both reached a caller as an
        # unworded `ToolError` and were counted as `_UNCLASSIFIED`. Unavailable is the honest
        # remedy: Graph did not give an answer this connector could use, and one retry then a
        # report is what to do about it.
        status = _STATUS[GraphUnavailable]
        raise GraphUnavailable(
            f"Microsoft Graph gave an answer this connector could not read: {error}",
            status=None,
            code=None,
            request_id=None,
        ) from error
    finally:
        # One reading of the clock for both instruments. Two calls would put two slightly different
        # durations on one call, and the difference would sit in the low end of the histograms —
        # exactly where a Graph call that answered from a warm pool lands.
        elapsed = perf_counter() - started
        if operation_level:
            record_graph_call(operation, status=status, seconds=elapsed)
        record_graph_step(operation, step=step, status=status, seconds=elapsed)


def _status_of(failure: GraphFailure) -> str:
    """The label for this failure. A subclass nobody has written yet counts as a plain failure."""
    return _STATUS.get(type(failure), _STATUS[GraphFailure])


def _sdk_spent_its_retries(failure: GraphThrottled) -> bool:
    """Whether the SDK retried this throttling before giving up on it.

    Throttling the SDK recovered from never reaches this module, so every throttling counted here is
    throttling that survived — and it survives in two ways with opposite remedies. The retry
    handler refuses to wait at all once the delay reaches its 180 s ceiling
    (`kiota_http/middleware/retry_handler.py:97`), so a `Retry-After` that long means no attempt was
    made and the answer is available later; anything shorter means `GraphSettings.max_retries`
    attempts were spent and the quota is genuinely gone.

    No header at all reads as retried, because that is what the SDK does with one: it falls back to
    exponential backoff, which is always under the ceiling.

    TRAP for whoever tunes `GraphSettings.max_retries`: that 180 s ceiling is per attempt, not
    cumulative. The SDK's `RetryHandlerOption` documents a `retry_time_limit` that would bound the
    total and never implements one, so three retries of a `Retry-After: 179` is about nine minutes
    of sleeping inside one MCP tool call, which is far past what an interactive client waits for.
    """
    advice = failure.retry_after_seconds
    return advice is None or advice < RetryHandlerOption.MAX_DELAY


# The statuses the SDK's retry handler acts on, borrowed rather than restated so that the two
# cannot disagree: `_is_throttling` below is only true of a status the handler really did wait
# `Retry-After` out on (`kiota_http/middleware/retry_handler.py:54` declares the set, `:140`
# consults it).
#
# Copied into a frozenset rather than aliased. `DEFAULT_RETRY_STATUS_CODES` is a mutable class
# attribute and `RetryHandler.__init__` hands that same object to every instance
# (`retry_handler.py:67`), so an alias here is a live write path into SDK state: one handler
# mutating `retry_on_status_codes` would silently change how this module classifies throttling
# service-wide. The frozenset keeps the borrow and drops the write path.
_RETRIED_BY_THE_SDK: frozenset[int] = frozenset(RetryHandler.DEFAULT_RETRY_STATUS_CODES)

_TOO_MANY_REQUESTS = 429


def _is_throttling(status: int | None, retry_after_seconds: float | None) -> bool:
    """Whether Graph held this caller off, rather than failing to serve it.

    A 429 always is, header or no header. Above that the two are told apart by the header alone:
    Graph rate limits with a 503 as well as with a 429, and a service that names the second it will
    answer again is one holding a caller off, not one that has fallen over. So precedence runs in
    that order — a 503 carrying `Retry-After` is throttling, a 503 without it is unavailability —
    and it matters because the remedies are opposite. Throttling is answered by waiting exactly as
    long as Graph asked and then by quota; an outage is answered by one retry and then by a report.
    Counted as an outage, throttling sends an operator after the wrong one of those, which is what
    `status="unavailable"` on a rate-limited connector used to do.

    Restricted to the statuses the SDK retries, which is what keeps `_sdk_spent_its_retries` true
    of the result: the handler takes its delay from `Retry-After` on exactly those, so a
    `Retry-After` on any other status was never waited out and `retried` would claim a retry that
    never happened. The Kiota handler reads a 503 with `Retry-After` the same way this does.
    """
    if status == _TOO_MANY_REQUESTS:
        return True
    return status in _RETRIED_BY_THE_SDK and retry_after_seconds is not None


def _classify(error: APIError) -> GraphFailure:
    status = error.response_status_code
    headers = _lowercase_headers(error)
    code = error.error.code if isinstance(error, ODataError) and error.error else None
    inner_code = _inner_code(error)
    request_id = headers.get("request-id")
    message = f"Microsoft Graph returned {status}" + (f" ({code})" if code else "")
    retry_after_seconds = _retry_after_seconds(headers)

    if _is_throttling(status, retry_after_seconds):
        return GraphThrottled(
            message,
            status=status,
            code=code,
            request_id=request_id,
            inner_code=inner_code,
            retry_after_seconds=retry_after_seconds,
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

    The SDK does not make the same choice — its own `_parse_retry_after` handles the date form — so
    the two disagree in exactly one case worth writing down. On a 503 carrying a date-form
    `Retry-After`, the SDK would wait it out and this module would read no delay, which makes
    `_is_throttling` false and files a rate limit under `unavailable`. Graph does not send that
    shape, which is why guessing is still the worse trade; if it ever starts, this is where it
    shows up.
    """
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
