"""What each Graph call cost, counted per operation and per step.

An **operation** is one tool call; a **step** is one Graph call inside it.

HARD RULE: both labels are names this code chose — `list_chats`, `resolve_meeting` — and never a
URL or a path. A label taken off a Graph URL is a new time series per chat, per message and per
meeting, and an unbounded label set takes a Prometheus down rather than showing up as a bad
dashboard. `tests/test_graph_metrics.py` enforces this over every module in `src/` and pins the
step vocabulary to an exact set.

The instruments are created on the OpenTelemetry *API* under the meter name `office_mcp/metrics.py`
uses, so both halves land in one instrumentation scope, and the API buffers instrument creation
until `configure_metrics` installs a provider, so nothing depends on import order. `metrics.py`
still owns the aggregation: the histogram buckets are views there, matched by instrument name.
"""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar

from opentelemetry import metrics

__all__ = [
    "GRAPH_OPERATIONS_TOTAL",
    "GRAPH_OPERATION_DURATION_SECONDS",
    "GRAPH_PAGES_SCANNED",
    "GRAPH_STEPS_TOTAL",
    "GRAPH_STEP_DURATION_SECONDS",
    "GRAPH_THROTTLED_TOTAL",
    "current_graph_operation",
    "graph_operation",
    "record_graph_call",
    "record_graph_step",
    "record_graph_throttled",
    "record_pages_scanned",
]

# Constants because the instruments below and the test that scrapes for them must agree: a test
# that spelled them again would pass over a typo.
GRAPH_OPERATIONS_TOTAL = "graph_operations_total"
GRAPH_OPERATION_DURATION_SECONDS = "graph_operation_duration_seconds"
GRAPH_THROTTLED_TOTAL = "graph_throttled_total"
GRAPH_PAGES_SCANNED = "graph_pages_scanned"
GRAPH_STEPS_TOTAL = "graph_steps_total"
GRAPH_STEP_DURATION_SECONDS = "graph_step_duration_seconds"

# Deliberately the whole service's name, not this package's own. The Prometheus exporter puts the
# meter name on every sample as `otel_scope_name`, so any instrument this service adds later under
# a scope of its own would split its metrics into two families of labels for no reader's benefit.
_METER_NAME = "office_mcp"

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
        "Wall-clock time one Graph operation took, including the SDK's Retry-After waits and every "
        "page a paged walk read. This is what an MCP client waited for, not what one HTTP request "
        "took."
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
        "call in a slow tool was the slow one; the operation histogram says only that the tool was "
        "slow."
    ),
)
_throttled = _meter.create_counter(
    GRAPH_THROTTLED_TOTAL,
    description=(
        "429s that outlived the SDK's retrying. `retried` says which of the two ways it survived: "
        "true when the retries were spent, false when Graph asked for a wait past the SDK's "
        "ceiling and none was attempted."
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

# How `collect_pages` learns which operation it is walking for, set by `graph_errors` around the
# block that makes the call.
_OPERATION: ContextVar[str | None] = ContextVar("office_mcp_graph_operation", default=None)


@contextmanager
def graph_operation(operation: str | None) -> Generator[None]:
    """Name the operation every Graph call inside this block is counted under.

    No name leaves the one in scope alone rather than clearing it: the nameless case is every
    `graph_step` block, and clearing there would hide the operation from `collect_pages` for the
    whole of a walk running inside one.
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

    Nothing is recorded without an operation. An `operation="unknown"` bucket would be worse than a
    missing series: a dashboard would show it as a real operation with real latency, hiding the tool
    that forgot to name itself inside it.
    """
    if operation is None:
        return
    _operations.add(1, {"operation": operation, "status": status})
    _operation_duration.record(seconds, {"operation": operation})


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
