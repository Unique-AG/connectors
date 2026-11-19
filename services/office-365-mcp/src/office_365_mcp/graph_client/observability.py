"""What each Graph call cost, counted per operation and per step.

An **operation** is one tool call. A **step** is one Graph call inside it.

HARD RULE: both labels are names this code chose — `teams_list_chats`, `resolve_meeting` — and
never a URL or a path. A label taken off a Graph URL is a new time series per chat, per message
and per meeting, and an unbounded label set takes a Prometheus down rather than showing up as a
bad dashboard. `tests/test_graph_metrics.py` enforces this over every module in `src/` and pins
the step vocabulary to an exact set.

The instruments are created on the OpenTelemetry *API* under the meter name
`office_365_mcp/metrics.py` uses, so both halves land in one instrumentation scope, and the API
buffers instrument creation until `configure_metrics` installs a provider, so nothing depends on
import order. `metrics.py` still owns the aggregation: the histogram buckets are views there,
matched by instrument name.
"""

from collections.abc import Generator, Iterable
from contextlib import contextmanager
from contextvars import ContextVar

from opentelemetry import metrics

__all__ = [
    "GRAPH_OPERATIONS_TOTAL",
    "GRAPH_OPERATION_DURATION_SECONDS",
    "GRAPH_PAGES_SCANNED",
    "GRAPH_STEPS_TOTAL",
    "GRAPH_STEP_DURATION_SECONDS",
    "GRAPH_SLOW_OPERATIONS_TOTAL",
    "GRAPH_THROTTLED_TOTAL",
    "SLOW_OPERATION_SECONDS",
    "GRAPH_TOKEN_ACQUISITIONS_TOTAL",
    "current_graph_operation",
    "graph_operation",
    "record_graph_call",
    "record_graph_step",
    "record_graph_throttled",
    "record_pages_scanned",
    "TOKEN_RESULTS",
    "record_token_acquisition",
    "start_operation_series",
]

# Constants because the instruments below and the test that scrapes for them must agree: restating
# them in a test hides a typo instead of catching one.
GRAPH_OPERATIONS_TOTAL = "graph_operations_total"
GRAPH_OPERATION_DURATION_SECONDS = "graph_operation_duration_seconds"
GRAPH_THROTTLED_TOTAL = "graph_throttled_total"
GRAPH_SLOW_OPERATIONS_TOTAL = "graph_slow_operations_total"
SLOW_OPERATION_SECONDS = 60.0
GRAPH_PAGES_SCANNED = "graph_pages_scanned"
GRAPH_STEPS_TOTAL = "graph_steps_total"
GRAPH_STEP_DURATION_SECONDS = "graph_step_duration_seconds"
GRAPH_TOKEN_ACQUISITIONS_TOTAL = "graph_token_acquisitions_total"

# Deliberately the whole service's name, not this package's own. The Prometheus exporter puts the
# meter name on every sample as `otel_scope_name`, so any instrument this service adds later under
# a scope of its own splits its metrics into two families of labels, for no reader's benefit.
_METER_NAME = "office_365_mcp"

_meter = metrics.get_meter(_METER_NAME)

_operations = _meter.create_counter(
    GRAPH_OPERATIONS_TOTAL,
    description=(
        "Microsoft Graph operations served on a caller's behalf, by operation and by outcome. One "
        "observation per tool call, not per HTTP request — a tool that makes three Graph calls "
        "counts once here and three times in graph_steps_total. `status` is the remedy class from "
        "graph_client/errors.py, not the HTTP code: the codes Graph can answer with are open-ended "
        "and sorting them into remedies is what that module is for."
    ),
)
_operation_duration = _meter.create_histogram(
    GRAPH_OPERATION_DURATION_SECONDS,
    unit="s",
    description=(
        "Wall-clock time of one tool call that attempted Graph. This includes the SDK's "
        "Retry-After waits and every page a paged walk read. It leaves out any wait a tool marked "
        "as not Microsoft's, such as `outlook_send_draft` asking a person to confirm. For the "
        "whole wait an MCP client saw, person included, read `mcp_call_duration_seconds`."
    ),
)
_steps = _meter.create_counter(
    GRAPH_STEPS_TOTAL,
    description=(
        "One Graph call inside an operation, by outcome. `step` is a name chosen in code for the "
        "call rather than for the tool, so a tool that reads three different Graph surfaces can be "
        "told apart by which of them answered badly."
    ),
)
_step_duration = _meter.create_histogram(
    GRAPH_STEP_DURATION_SECONDS,
    unit="s",
    description=(
        "Wall-clock time one Graph call inside an operation took. This is the axis that says which "
        "call in a slow tool was the slow one. The operation histogram says only that the tool was "
        "slow."
    ),
)
_slow_operations = _meter.create_counter(
    GRAPH_SLOW_OPERATIONS_TOTAL,
    description=(
        "Tool calls that attempted Graph and took more than 60 seconds, the time after which Kong "
        "and the chat close the request. Measured like graph_operation_duration_seconds."
    ),
)
_throttled = _meter.create_counter(
    GRAPH_THROTTLED_TOTAL,
    description=(
        "Throttling answers that outlived the SDK's retrying. `retried` is true when the SDK "
        "retried the request, and false when it did not: Graph asked for a wait past the SDK's "
        "ceiling, or the call allows no retry."
    ),
)
_token_acquisitions = _meter.create_counter(
    GRAPH_TOKEN_ACQUISITIONS_TOTAL,
    description=(
        "Graph tokens a tool call asked for on the caller's behalf, by tool and by result. A token "
        "the SDK serves from its cache counts as ok. `refused` is an answer from Entra with an "
        "AADSTS code, and is never cached. `failed` is any other failure, such as a network "
        "error. A tool call without a token never reaches Graph."
    ),
)
_pages_scanned = _meter.create_histogram(
    GRAPH_PAGES_SCANNED,
    description=(
        "Pages one paged walk read to answer one call, the first request included. A walk is "
        "bounded by the item scan cap rather than by a page count, so this is where the cost of "
        "that cap shows up."
    ),
)

# How `collect_pages` learns which operation it is walking for, set by `measured_graph_operation`
# around the tool call.
_OPERATION: ContextVar[str | None] = ContextVar("office_365_mcp_graph_operation", default=None)


@contextmanager
def graph_operation(operation: str | None) -> Generator[None]:
    """Name the operation every Graph call inside this block is counted under.

    No name leaves the one already in scope alone, rather than clearing it. The nameless case is
    every `graph_step` block, and clearing the operation there hides it from `collect_pages` for
    the whole of a walk that runs inside one.
    """
    if operation is None:
        yield
        return
    token = _OPERATION.set(operation)
    try:
        yield
    finally:
        _OPERATION.reset(token)


def current_graph_operation() -> str | None:
    return _OPERATION.get()


def record_graph_call(operation: str | None, *, status: str, seconds: float) -> None:
    """Count one Graph operation and how long it took.

    Nothing is recorded without an operation. An `operation="unknown"` bucket is worse than a
    missing series: a dashboard shows it as a real operation with real latency, and that hides the
    tool that forgot to name itself inside it.
    """
    if operation is None:
        return
    _operations.add(1, {"operation": operation, "status": status})
    _operation_duration.record(seconds, {"operation": operation})
    if seconds > SLOW_OPERATION_SECONDS:
        _slow_operations.add(1, {"operation": operation})


def record_graph_step(
    operation: str | None, *, step: str | None, status: str, seconds: float
) -> None:
    """Count one Graph call inside an operation and how long it took.

    Both names are required, for the reason `record_graph_call` requires one.
    """
    if operation is None or step is None:
        return
    _steps.add(1, {"operation": operation, "step": step, "status": status})
    _step_duration.record(seconds, {"operation": operation, "step": step})


def record_graph_throttled(operation: str | None, *, retried: bool) -> None:
    if operation is None:
        return
    _throttled.add(1, {"operation": operation, "retried": str(retried).lower()})


def record_pages_scanned(operation: str | None, pages: int) -> None:
    if operation is None:
        return
    _pages_scanned.record(pages, {"operation": operation})


TOKEN_RESULTS: tuple[str, ...] = ("ok", "refused", "failed")


def record_token_acquisition(operation: str | None, *, result: str) -> None:
    assert result in TOKEN_RESULTS, f"unknown token result {result!r}"
    if operation is None:
        return
    _token_acquisitions.add(1, {"operation": operation, "result": result})


def start_operation_series(operations: Iterable[str], *, statuses: Iterable[str]) -> None:
    status_values = tuple(statuses)
    for operation in operations:
        for status in status_values:
            _operations.add(0, {"operation": operation, "status": status})
        _slow_operations.add(0, {"operation": operation})
        for retried in ("true", "false"):
            _throttled.add(0, {"operation": operation, "retried": retried})
        for result in TOKEN_RESULTS:
            _token_acquisitions.add(0, {"operation": operation, "result": result})
