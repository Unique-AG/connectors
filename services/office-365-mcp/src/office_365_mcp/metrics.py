from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from unique_toolkit.monitoring import REGISTRY as _TOOLKIT_REGISTRY

from office_365_mcp.config import AppConfig
from office_365_mcp.graph_client import (
    GRAPH_OPERATION_DURATION_SECONDS,
    GRAPH_PAGES_SCANNED,
    GRAPH_STEP_DURATION_SECONDS,
)

_provider: MeterProvider | None = None

# No instrument is declared in this module. It installs the meter provider, and owns one thing about
# the instruments declared elsewhere: their aggregation. The `graph_*` family —
# `graph_operations_total`, `graph_operation_duration_seconds`, `graph_throttled_total`,
# `graph_pages_scanned`, `graph_steps_total` and `graph_step_duration_seconds` — is created in
# `graph_client/observability.py`, which imports nothing of this application. The provider installed
# below is what gives those instruments somewhere to record.
#
# The layout `app.py` hands `setup_ops` for the inbound histogram: `prometheus_client`'s own
# defaults, whose top finite boundary is 10 s, plus 30/60/120/300. A dashboard that puts inbound MCP
# latency beside outbound Graph latency can then read one against the other without correcting for
# the boundaries. The layout must reach minutes because these instruments time the SDK's Retry-After
# waits too: `GraphSettings` documents four attempts at its 30 s request timeout, and each wait
# between them is capped at kiota's `RetryHandlerOption.MAX_DELAY` of 180 s. 300 s does not cover
# that worst case, but it tells a throttled call apart from a slow one, which a 10 s ceiling cannot.
#
# One tuple serves both Graph latency histograms, so an operation and the steps inside it read on
# the same scale. Two separate literals can drift out of sync, and a step quantile on a scale that
# does not match the operation quantile above it answers only half a question.
_GRAPH_LATENCY_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.075,
    0.1,
    0.25,
    0.5,
    0.75,
    1.0,
    2.5,
    5.0,
    7.5,
    10.0,
    30.0,
    60.0,
    120.0,
    300.0,
)

# Three histograms have default buckets that answer the wrong question. This module corrects them
# here rather than where they are declared: a bucket layout is an aggregation, an aggregation
# belongs to the provider, and a view matches on the instrument's name, so this needs nothing from
# the module that records it.
#
# The OpenTelemetry default layout runs 0, 5, 10, 25 … 10000, which is minutes-shaped. That default
# layout lands nearly every observation of the three — one page read, or a call that took well under
# five seconds — in the first bucket, so every quantile reads the same.
_VIEWS = (
    View(
        instrument_name=GRAPH_OPERATION_DURATION_SECONDS,
        aggregation=ExplicitBucketHistogramAggregation(_GRAPH_LATENCY_BUCKETS),
    ),
    View(
        instrument_name=GRAPH_STEP_DURATION_SECONDS,
        aggregation=ExplicitBucketHistogramAggregation(_GRAPH_LATENCY_BUCKETS),
    ),
    View(
        instrument_name=GRAPH_PAGES_SCANNED,
        # Nearly every walk reads one page. A walk that gives up lands just past 10
        # (`MAX_EMPTY_PAGES`), and only the item scan cap bounds anything above that.
        aggregation=ExplicitBucketHistogramAggregation((1, 2, 3, 5, 10, 25, 50, 100, 250, 1000)),
    ),
)


def configure_metrics(config: AppConfig) -> MeterProvider:
    """Trap: `/metrics` reads `unique_toolkit.monitoring.REGISTRY`, not `prometheus_client`'s
    default registry. Point the reader at it explicitly, or metrics never appear in a scrape."""
    global _provider
    if _provider is not None:
        return _provider
    resource = Resource.create({SERVICE_NAME: "office-365-mcp", SERVICE_VERSION: config.version})
    reader = PrometheusMetricReader(registry=_TOOLKIT_REGISTRY)
    provider = MeterProvider(resource=resource, metric_readers=[reader], views=list(_VIEWS))
    metrics.set_meter_provider(provider)
    _provider = provider
    return provider
