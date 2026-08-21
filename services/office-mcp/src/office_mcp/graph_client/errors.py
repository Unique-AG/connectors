"""Graph failures sorted by remedy.

The SDK reports all failures as `APIError` with a status code. This module categorises them once so
each caller does not re-derive the remedy:

- `GraphThrottled` (429, or a retriable 5xx that named a delay): retriable, and Graph supplies
  Retry-After.
- `GraphForbidden` (401 or 403): the token lacks permission.
- `GraphNotFound` (404): not found, or not visible.
- `GraphUnavailable` (a 5xx with nothing to wait for, or no response): service down or unreachable.

Anything else (400, 409) raises `GraphFailure`. Those status codes suggest no remedy.

`GraphPagingUnending` is the one that is not a failed request: Graph answering 200 after 200 with
nothing in them while still advertising more of a collection, which no status code describes and
the SDK therefore cannot report. It is a `GraphFailure` so that `shared/seam.py` carries it to the
caller as advice rather than as a crash. See its class docstring.

`inner_code` is Graph's `error.innerError.code`, carried alongside the status. Where a status and
an outer code are the same for two failures with opposite remedies, it is the only field that tells
them apart: the transcript APIs answer both "your tenant has switched Graph access to transcripts
off, and no app can switch it back on" and "this tenant will not give you speaker names, ask for
the unattributed format" as `403 Forbidden` with `code: Forbidden`, and Microsoft's own instruction
is to "branch on the `innerError.code` value, not the message text. Messages are subject to change"
(https://learn.microsoft.com/en-us/graph/api/calltranscript-get). It is data like `status` is, not
a category: a subclass per inner code would be a subclass per Graph feature.

Some failures reach a caller that Graph never described with a status code at all. Three are the
SDK failing rather than Graph refusing, and all three become `GraphUnavailable`, because none
carries a status, a code or a request id and all three mean one thing: no answer arrived that this
connector could use. `CancelledError` is the caller going away, and is re-raised untranslated.
`_measured` says what each one is.

`graph_errors` also counts and times the operation it wraps, and `graph_step` counts one Graph call
inside it. They are the seam every Graph call already goes through, and the categories above are
exactly the `status` a counter wants, so measuring anywhere else would mean re-deriving them. The
instruments live in `graph_client/observability.py`.
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
    """Graph request failure. The subclass is the remedy. Support needs `request_id`.

    `inner_code` defaults to `None`: most Graph errors carry no inner code worth branching on, and
    where one does, it is the whole of the difference.
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
    """Rate limit from Graph that the SDK's retries did not outlast.

    Obey the Retry-After header for the fastest recovery: usage keeps accruing while throttled, so
    an early retry only extends the wait. Reaching here means the SDK retried
    `GraphSettings.max_retries` times, or Retry-After asked for more than the SDK's 180 s wait
    ceiling and it gave up. `None` means Graph sent no header, so choose your own backoff.

    TRAP: this is not only 429. Graph also holds a caller off with a 5xx that carries Retry-After,
    and `status` tells the two apart: a 429 is quota, a 503 with a delay may be quota or load
    shedding. The delay is the remedy either way, so they are one class. See `_is_throttling`."""

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
    """Graph refused the caller, not the request. TRAP: 401 (token rejected) and 403 (no scope) are
    both forbidden, and `status` tells them apart. 401 means sign in again, 403 means ask an
    administrator."""


class GraphNotFound(GraphFailure):
    """TRAP: Graph returns 404 for both not-found and not-visible. Cannot prove absence."""


class GraphUnavailable(GraphFailure):
    """Graph returned a 5xx with nothing to wait for, timed out, or could not be reached. Usually
    transient. TRAP: some 500s are permanent for certain content (Loop components, certain cards),
    where retries spin forever. A 5xx that did name a delay is `GraphThrottled`: the remedy there
    is the delay, and counting it here would read on a dashboard as an outage."""


class GraphPagingUnending(GraphFailure):
    """Graph would not end a collection: a run of empty pages, every one advertising more.

    Not a failed request, since each of those pages was a 200, so it carries no status, no code and
    no request id, and `_classify` never produces it. `pagination.collect_pages` raises it directly
    when the run exceeds `pagination.MAX_EMPTY_PAGES`, and `empty_pages` is how long that run was.

    A raise rather than an `assert`, for two reasons. `python -O` strips asserts, and that bound is
    the only thing between a collection that answers nothing but empty pages and a walk that
    follows them until throttling or a timeout ends it. And Graph misbehaving is the boundary this
    module exists to describe, not an invariant of this connector's own code.
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

# Every value the `status` label can take, so a reader can see the set and a test can assert it.
# Public because a dashboard has to decide, for each one, whether it counts as a failure, and
# `cancelled` is the one that answers differently from every other non-`ok` value.
GRAPH_STATUSES: frozenset[str] = frozenset({*_STATUS.values(), _OK, _UNCLASSIFIED, _CANCELLED})


@contextmanager
def graph_errors(operation: str, *, step: str | None = None) -> Generator[None]:
    """Translate SDK failures into Graph error types, and count what the operation cost.

    `operation` is the name this call is counted under. Pass the tool's own `TOOL_NAME`. It must be
    chosen in code and never taken off the URL. `observability.py` says why that is a hard rule
    rather than a preference. It is required, because a tool that left it out would be missing from
    every Graph dashboard with nothing at the call site to say so. A test driving the SDK directly
    names itself like anything else does.

    `step` names one Graph call inside this block for the finer-grained instruments, for the tool
    that makes exactly one. A tool that makes several uses `graph_step` around each instead.
    """
    with _measured(operation, step=step):
        yield


@contextmanager
def graph_step(step: str) -> Generator[None]:
    """Measure one Graph call inside the `graph_errors` block already in scope.

    In a tool that makes several Graph calls, the operation-level instruments answer "what did this
    tool call cost" and the step-level ones answer "which Graph call inside it was slow". The
    operation comes from the block above rather than from an argument, because it is already in
    scope and a second argument would be a second thing to keep in agreement with the first.

    Outside any `graph_errors` block there is no operation to attribute a step to, so nothing is
    recorded. `record_graph_call` keeps the same rule for the same reason.
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
    except Exception as error:
        # SDK failures that are not `APIError` and carry no response to classify. Three shapes, and
        # all three used to reach a caller as an unworded `ToolError` counted under
        # `_UNCLASSIFIED`.
        #
        # `KiotaHTTPXError` is the SDK's own family. Two of that family are reachable from a
        # Graph call: `RedirectError` when the redirect handler gives up
        # (`kiota_http/middleware/redirect_handler.py:94`), and `ResponseError` when the adapter
        # gets no response to read (`kiota_http/httpx_request_adapter.py:602`).
        #
        # A bare `Exception` is the SDK failing to read what Graph sent. The parse-node registry
        # raises the base class for a content type it has no parser for
        # (`kiota_abstractions/serialization/parse_node_factory_registry.py:48`), which is what a
        # gateway answering `text/html` on a 500 in front of Graph produces. No `error_map` can
        # describe that, because the body never became a model.
        #
        # TRAP: the *exact* base class is the discriminator, and `isinstance` here would be a bug.
        # Nothing in this service raises `Exception` itself (an internal invariant is an `assert`, a
        # boundary is a typed raise), so any subclass reaching here is this connector's own fault,
        # not Graph's. Those keep travelling untranslated and stay `_UNCLASSIFIED`: a bug of ours
        # reported as `GraphUnavailable` tells an operator to retry and blames Microsoft for it.
        if not isinstance(error, KiotaHTTPXError) and type(error) is not Exception:
            raise
        # Unavailable is the honest remedy for both: Graph did not give an answer this connector
        # could use, and one retry then a report is what to do about it.
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

    Throttling the SDK recovered from never reaches this module, so every throttling counted here
    survived, and it survives in two ways with opposite remedies. The retry handler refuses to wait
    at all once the delay reaches its 180 s ceiling
    (`kiota_http/middleware/retry_handler.py:97`), so a `Retry-After` that long means no attempt
    was made and the answer is available later. Anything shorter means `GraphSettings.max_retries`
    attempts were spent and the quota is genuinely gone.

    No header at all reads as retried, because the SDK falls back to exponential backoff, which is
    always under the ceiling.

    TRAP for whoever tunes `GraphSettings.max_retries`: that 180 s ceiling is per attempt, not
    cumulative. The SDK's `RetryHandlerOption` documents a `retry_time_limit` that would bound the
    total and never implements one, so three retries of a `Retry-After: 179` is about nine minutes
    of sleeping inside one MCP tool call, far past what an interactive client waits for.
    """
    advice = failure.retry_after_seconds
    return advice is None or advice < RetryHandlerOption.MAX_DELAY


# The statuses the SDK's retry handler acts on, borrowed rather than restated so the two cannot
# disagree: `_is_throttling` below is only true of a status the handler really did wait
# `Retry-After` out on (`kiota_http/middleware/retry_handler.py:54` declares the set, `:140`
# consults it).
#
# Copied into a frozenset rather than aliased. `DEFAULT_RETRY_STATUS_CODES` is a mutable class
# attribute and `RetryHandler.__init__` hands that same object to every instance
# (`retry_handler.py:67`), so an alias here is a live write path into SDK state: one handler
# mutating `retry_on_status_codes` would change how this module classifies throttling service-wide.
_RETRIED_BY_THE_SDK: frozenset[int] = frozenset(RetryHandler.DEFAULT_RETRY_STATUS_CODES)

_TOO_MANY_REQUESTS = 429


def _is_throttling(status: int | None, retry_after_seconds: float | None) -> bool:
    """Whether Graph held this caller off, rather than failing to serve it.

    A 429 always is, header or no header. Above that the header alone tells the two apart: Graph
    rate limits with a 503 as well as with a 429, and a service that names the second it will
    answer again is holding a caller off, not falling over. So a 503 carrying `Retry-After` is
    throttling and a 503 without one is unavailability, and the difference matters because the
    remedies are opposite. Throttling is answered by waiting exactly as long as Graph asked, then
    by quota. An outage is answered by one retry, then by a report. Counted as an outage, throttling
    sends an operator after the wrong one. That is what `status="unavailable"` on a rate-limited
    connector used to do.

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
    """`response_headers` as a dict with lowercased keys.

    The declared type is `dict[str, str]`, but the request adapter may assign `httpx.Headers`
    instead. `httpx.Headers` is case-insensitive, and lowercasing makes both forms behave alike.
    """
    return {name.lower(): value for name, value in (error.response_headers or {}).items()}


def _retry_after_seconds(headers: dict[str, str]) -> float | None:
    """Parse the Retry-After header as delay-seconds, or `None`.

    Graph documents this header as delay-seconds and never sends the legal HTTP-date form here.
    This parser does not guess at that form: a wrong guess about the caller's clock is worse than
    reporting no advice.

    The SDK's own `_parse_retry_after` does handle the date form, so the two disagree in one case.
    On a 503 carrying a date-form Retry-After, the SDK would wait it out and this module would read
    no delay, making `_is_throttling` false and filing a rate limit under `unavailable`. Graph does
    not send that shape, so guessing is still the worse trade. If it ever starts, this is where it
    shows up.
    """
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
