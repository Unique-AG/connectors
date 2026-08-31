"""Graph failures sorted by remedy: the subclass is the remedy, and `GraphFailure` means none known.

`inner_code` is Graph's `error.innerError.code`. TRAP: it is sometimes the only field separating two
failures with opposite remedies. The transcript APIs answer both "this tenant has switched Graph
access to transcripts off" and "this tenant will not give you speaker names, ask for the
unattributed format" as `403 Forbidden` with `code: Forbidden`, and Microsoft's own instruction is
to "branch on the `innerError.code` value, not the message text"
(https://learn.microsoft.com/en-us/graph/api/calltranscript-get).
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

from office_365_mcp.graph_client.observability import (
    current_graph_operation,
    graph_operation,
    record_graph_call,
    record_graph_step,
    record_graph_throttled,
)


class GraphFailure(Exception):
    """Support needs `request_id`."""

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
    """Graph held this caller off, and the SDK's retries did not outlast it.

    TRAP: not only 429. Graph also holds a caller off with a 5xx carrying Retry-After. Usage keeps
    accruing while throttled, so retrying before `retry_after_seconds` only extends the wait. `None`
    there means no header came, and the backoff is yours to choose."""

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
    """TRAP: 401 (token rejected) and 403 (no scope) are both forbidden, and `status` tells them
    apart. 401 means sign in again, 403 means ask an administrator."""


class GraphNotFound(GraphFailure):
    """TRAP: Graph returns 404 for both not-found and not-visible. Cannot prove absence."""


class GraphUnavailable(GraphFailure):
    """Graph returned a 5xx with nothing to wait for, timed out, or was unreachable. Usually
    transient. TRAP: some 500s are permanent for certain content (Loop components, certain cards),
    where retries spin forever."""


class GraphPagingUnending(GraphFailure):
    """Graph does not end a collection: a run of empty pages, every one advertising more.

    TRAP: not a failed request. Every one of those pages was a 200, so status, code and request id
    are all None, and `_classify` never produces this. `pagination.collect_pages` raises it
    directly.
    """

    def __init__(self, message: str, *, empty_pages: int) -> None:
        super().__init__(message, status=None, code=None, request_id=None)
        self.empty_pages: int = empty_pages


_STATUS: dict[type[GraphFailure], str] = {
    GraphThrottled: "throttled",
    GraphForbidden: "forbidden",
    GraphNotFound: "not_found",
    GraphUnavailable: "unavailable",
    GraphPagingUnending: "paging_unending",
    GraphFailure: "failed",
}

_OK = "ok"

# Not "failed": a Graph status must mean Graph said something.
_UNCLASSIFIED = "error"

# Its own label because cancellation happens routinely, and counted as `error` it reads on a
# dashboard as this connector failing.
_CANCELLED = "cancelled"

GRAPH_STATUSES: frozenset[str] = frozenset({*_STATUS.values(), _OK, _UNCLASSIFIED, _CANCELLED})


@contextmanager
def graph_errors(operation: str, *, step: str | None = None) -> Generator[None]:
    """Translate SDK failures into Graph error types, and count what the operation cost.

    `operation` is the tool's own `TOOL_NAME`, never anything taken off a URL — see
    `observability.py`. `step` names the single Graph call inside this block, for a tool that makes
    exactly one. A tool that makes several uses `graph_step` instead.
    """
    with _measured(operation, step=step):
        yield


@contextmanager
def graph_step(step: str) -> Generator[None]:
    """Measure one Graph call inside the `graph_errors` block in scope.

    Outside any such block there is no operation to attribute the step to, and nothing is recorded.
    """
    with _measured(current_graph_operation(), step=step, operation_level=False):
        yield


@contextmanager
def _measured(
    operation: str | None, *, step: str | None, operation_level: bool = True
) -> Generator[None]:
    """`operation_level` is False for a step inside an operation: the outer block already counts the
    whole thing, and counting twice turns `graph_operations_total` into a count of blocks entered.
    """
    started = perf_counter()
    # Pessimistic on purpose: every path below replaces it, so this surviving means an exception
    # escaped that this seam cannot describe.
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
        # DNS, connect, or read timeout: no HTTP response exists yet, and the request adapter raises
        # `APIError` only once one does, so this never reaches the clause above.
        status = _STATUS[GraphUnavailable]
        raise GraphUnavailable(
            f"Microsoft Graph was unreachable: {error}",
            status=None,
            code=None,
            request_id=None,
        ) from error
    except GraphFailure as failure:
        # Raised inside the block, not translated here: `collect_pages` refusing an unending
        # collection is the one that happens.
        status = _status_of(failure)
        raise
    except CancelledError:
        # Re-raised untranslated: cancellation must continue to propagate as itself, or the task
        # group that sent it never learns it was obeyed.
        status = _CANCELLED
        raise
    except Exception as error:
        # SDK failures that are not `APIError` and carry no response to classify. `KiotaHTTPXError`
        # reaches here as `RedirectError` (`kiota_http/middleware/redirect_handler.py:94`) or
        # `ResponseError` (`kiota_http/httpx_request_adapter.py:602`). A bare `Exception` is what
        # the parse-node registry raises when it meets a content type that has no parser
        # (`kiota_abstractions/serialization/parse_node_factory_registry.py:48`). A gateway that
        # answers `text/html` on a 500 produces exactly that, and no `error_map` can describe it.
        #
        # TRAP: the *exact* base class is the discriminator here, not `isinstance`, which matches
        # every subclass too. Nothing in this service raises `Exception` itself, so any subclass
        # reaching here is our own bug. `GraphUnavailable` always tells an operator to retry and
        # blame Microsoft, the wrong message for our own bug.
        if not isinstance(error, KiotaHTTPXError) and type(error) is not Exception:
            raise
        status = _STATUS[GraphUnavailable]
        raise GraphUnavailable(
            f"Microsoft Graph gave an answer this connector could not read: {error}",
            status=None,
            code=None,
            request_id=None,
        ) from error
    finally:
        # One reading of the clock serves both instruments. Two readings land two different
        # durations in the low end of the histograms, exactly where a call answered from a warm
        # pool sits.
        elapsed = perf_counter() - started
        if operation_level:
            record_graph_call(operation, status=status, seconds=elapsed)
        record_graph_step(operation, step=step, status=status, seconds=elapsed)


def _status_of(failure: GraphFailure) -> str:
    return _STATUS.get(type(failure), _STATUS[GraphFailure])


def _sdk_spent_its_retries(failure: GraphThrottled) -> bool:
    """Whether the SDK retried this throttling before giving up on it.

    The retry handler refuses to wait at all once the delay reaches its 180 s ceiling
    (`kiota_http/middleware/retry_handler.py:97`), so a `Retry-After` that long means no attempt was
    made. Anything shorter, or no header, means `GraphSettings.max_retries` were spent.

    TRAP for whoever tunes `GraphSettings.max_retries`: that ceiling is per attempt, not cumulative.
    `RetryHandlerOption` documents a `retry_time_limit` meant to bound the total, and never
    implements one, so three retries of a `Retry-After: 179` is nine minutes inside one tool call.
    """
    advice = failure.retry_after_seconds
    return advice is None or advice < RetryHandlerOption.MAX_DELAY


# Borrowed rather than restated so the two cannot disagree
# (`kiota_http/middleware/retry_handler.py:54` declares the set, `:140` consults it). TRAP: copied
# into a frozenset, not aliased. `DEFAULT_RETRY_STATUS_CODES` is a mutable class attribute and
# `RetryHandler.__init__` hands that same object to every instance (`retry_handler.py:67`), so an
# alias is a live write path into SDK state: one handler that mutates `retry_on_status_codes`
# changes how this module classifies throttling service-wide.
_RETRIED_BY_THE_SDK: frozenset[int] = frozenset(RetryHandler.DEFAULT_RETRY_STATUS_CODES)

_TOO_MANY_REQUESTS = 429


def _is_throttling(status: int | None, retry_after_seconds: float | None) -> bool:
    """Whether Graph held this caller off, rather than a failure to serve it.

    Restricted to the statuses the SDK retries, which is what keeps `_sdk_spent_its_retries`
    accurate: the handler takes its delay from `Retry-After` only on those statuses. On any other
    status the handler never waits out `Retry-After`, so marking it `retried` misreports a retry
    that never happened.
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
    `date` and none for `code`, so it arrives untyped in `additional_data`, hence the narrowing.
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
    """TRAP: `response_headers` is declared `dict[str, str]`, but the request adapter can assign the
    case-insensitive `httpx.Headers` instead. Lowercasing makes both forms behave alike.
    """
    return {name.lower(): value for name, value in (error.response_headers or {}).items()}


def _retry_after_seconds(headers: dict[str, str]) -> float | None:
    """Parse the Retry-After header as delay-seconds, or `None`.

    Graph never sends the legal HTTP-date form here, and a wrong guess about the caller's clock is
    worse than no advice. TRAP: the SDK's own `_parse_retry_after` does handle the date form, so on
    a 503 carrying one, the SDK waits it out while this function reads no delay. That makes
    `_is_throttling` return false and files the rate limit under `unavailable` instead.
    """
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
