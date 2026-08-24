from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from unique_toolkit.monitoring import REGISTRY as _TOOLKIT_REGISTRY

from office_mcp.config import AppConfig
from office_mcp.graph_client import (
    GRAPH_OPERATION_DURATION_SECONDS,
    GRAPH_PAGES_SCANNED,
    GRAPH_STEP_DURATION_SECONDS,
)

_provider: MeterProvider | None = None

# No instrument is declared in this module. It installs the meter provider, and owns one thing about
# the instruments declared elsewhere: their aggregation. The `graph_*` family —
# `graph_operations_total`, `graph_operation_duration_seconds`, `graph_throttled_total`,
# `graph_pages_scanned`, `graph_steps_total` and `graph_step_duration_seconds` — is created in
# `graph_client/observability.py`, which imports nothing of this application; the provider installed
# below is what gives those instruments somewhere to record.
#
# The layout `app.py` hands `setup_ops` for the inbound histogram: `prometheus_client`'s own
# defaults, whose top finite boundary is 10 s, plus 30/60/120/300. A dashboard that puts inbound MCP
# latency beside outbound Graph latency can then read one against the other without correcting for
# the boundaries. It has to reach minutes because these instruments time the SDK's Retry-After waits
# too: `GraphSettings` documents four attempts at its 30 s request timeout, and each wait between
# them is capped at kiota's `RetryHandlerOption.MAX_DELAY` of 180 s. 300 s does not cover that worst
# case, but it tells a throttled call apart from a slow one, which a 10 s ceiling cannot.
#
# One tuple for both Graph latency histograms, so an operation and the steps inside it are read on
# the same scale. Two literals would drift, and a step quantile that could not be compared with the
# operation quantile above it would answer half a question.
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

# Three histograms whose default buckets would answer the wrong question, corrected here rather than
# where they are declared: a bucket layout is an aggregation, an aggregation is the provider's, and
# a view matches on the instrument's name, so this needs nothing from the module that records it.
#
# The OpenTelemetry default layout runs 0, 5, 10, 25 … 10000, which is minutes-shaped. Nearly every
# observation of any of the three — one page read, or a call that took well under five seconds —
# would land in the first bucket, and every quantile would read the same.
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
    resource = Resource.create({SERVICE_NAME: "office-mcp", SERVICE_VERSION: config.version})
    reader = PrometheusMetricReader(registry=_TOOLKIT_REGISTRY)
    provider = MeterProvider(resource=resource, metric_readers=[reader], views=list(_VIEWS))
    metrics.set_meter_provider(provider)
    _provider = provider
    return provider
