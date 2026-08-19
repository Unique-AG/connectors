"""What each Graph call cost, counted per operation.

Four series, and the one label that decides whether they are readable:

* `graph_requests_total{operation, status}` — every Graph call this connector made, by outcome.
* `graph_request_duration_seconds{operation}` — how long one took, end to end, retries included.
* `graph_throttled_total{operation, retried}` — the 429s that outlived the SDK's own retrying.
* `graph_pages_scanned{operation}` — how many pages one paged walk read.

`operation` is a name this code chose — one per tool, `list_chats`, `search_messages` — and never a
URL or a path. That is the whole rule and it is not a style preference: a label taken off a Graph
URL is a new time series per chat, per message and per meeting, and an unbounded label set takes a
Prometheus down rather than showing up as a bad dashboard. Graph URLs here are made of almost
nothing else, so the name has to come from the caller, which is why `graph_errors` takes it and
this module never derives it.

Architectural rationale: the instruments live here rather than beside the rest of this service's
domain instruments in `office_mcp/metrics.py`, because `graph_client/` imports nothing of this
application and an instrument is not a knob `GraphSettings` could carry. They are created on the
OpenTelemetry *API* under the meter name `metrics.py` uses, so both halves land in one
instrumentation scope; the API buffers instrument creation until `configure_metrics` installs a
provider, so nothing depends on import order. What `metrics.py` still owns is the aggregation —
the histogram buckets are views there, matched by instrument name, which needs no import either
way.
"""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar

from opentelemetry import metrics

__all__ = [
    "GRAPH_PAGES_SCANNED",
    "GRAPH_REQUESTS_TOTAL",
    "GRAPH_REQUEST_DURATION_SECONDS",
    "GRAPH_THROTTLED_TOTAL",
    "current_graph_operation",
    "graph_operation",
    "record_graph_call",
    "record_graph_throttled",
    "record_pages_scanned",
]

# The names, as constants, because two readers need to agree on them: the instruments below and the
# test that scrapes for them. A test that spelled them again would pass over a typo.
GRAPH_REQUESTS_TOTAL = "graph_requests_total"
GRAPH_REQUEST_DURATION_SECONDS = "graph_request_duration_seconds"
GRAPH_THROTTLED_TOTAL = "graph_throttled_total"
GRAPH_PAGES_SCANNED = "graph_pages_scanned"

# Deliberately the meter name `office_mcp/metrics.py` uses, not one of this package's own. The
# Prometheus exporter puts the meter name on every sample as `otel_scope_name`, so a second scope
# would split this service's own metrics into two families of labels for no reader's benefit.
_METER_NAME = "office_mcp"

_meter = metrics.get_meter(_METER_NAME)

_requests = _meter.create_counter(
    GRAPH_REQUESTS_TOTAL,
    description=(
        "Microsoft Graph calls made on a caller's behalf, by operation and by outcome. `status` is "
        "the remedy class from graph_client/errors.py, not the HTTP code: the codes Graph can "
        "answer with are open-ended and sorting them into remedies is what that module is for."
    ),
)
_duration = _meter.create_histogram(
    GRAPH_REQUEST_DURATION_SECONDS,
    unit="s",
    description=(
        "Wall-clock time one Graph operation took, including the SDK's Retry-After waits and every "
        "page a paged walk read. This is what an MCP client waited for, not what one HTTP request "
        "took."
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

# How `collect_pages` learns which operation it is walking for. Set once, by `graph_errors`, around
# the block that makes the call; a walk is always inside one, because a walk outside one lets an
# unclassified SDK error escape to a tool. Threading the name through `collect_pages` as well would
# be a second argument to keep in agreement with the first, for a value that is already in scope.
_OPERATION: ContextVar[str | None] = ContextVar("office_mcp_graph_operation", default=None)


@contextmanager
def graph_operation(operation: str | None) -> Generator[None]:
    """Name the operation every Graph call inside this block is counted under."""
    token = _OPERATION.set(operation)
    try:
        yield
    finally:
        _OPERATION.reset(token)


def current_graph_operation() -> str | None:
    """The operation now being served, or None outside any `graph_errors` block."""
    return _OPERATION.get()


def record_graph_call(operation: str | None, *, status: str, seconds: float) -> None:
    """Count one Graph operation and how long it took.

    Nothing is recorded without an operation. An `operation="unknown"` bucket would be worse than
    a missing series: a dashboard would show it as a real operation with real latency, and the tool
    that forgot to name itself would be invisible inside it.
    """
    if operation is None:
        return
    _requests.add(1, {"operation": operation, "status": status})
    _duration.record(seconds, {"operation": operation})


def record_graph_throttled(operation: str | None, *, retried: bool) -> None:
    """Count one 429 that reached a caller."""
    if operation is None:
        return
    _throttled.add(1, {"operation": operation, "retried": str(retried).lower()})


def record_pages_scanned(operation: str | None, pages: int) -> None:
    """Record how many pages one walk read."""
    if operation is None:
        return
    _pages_scanned.record(pages, {"operation": operation})
