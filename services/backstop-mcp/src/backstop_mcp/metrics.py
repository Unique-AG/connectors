from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource

from backstop_mcp.config import AppConfig

_provider: MeterProvider | None = None

# The two `catalog_*_duration_seconds` histograms — demand and walk, see `CATALOG_GET_DURATION`
# below — are read as one view: subtract their `_count`s and the difference is the requests a TTL
# would have removed. Comparing them bucket-for-bucket only means something if the buckets are
# identical, so one View defines them for both rather than each instrument carrying its own copy.
#
# A catalog walk is many paginated requests, not one: the custom-field schema is ~1000
# definitions over many pages, while the activity-tag list is a handful. The default OTel
# boundaries are shaped for milliseconds-as-integers and would put every one of these in the
# first bucket, hence sub-second resolution for the short catalogs and headroom past 30s for the
# schema walk, which is the one this exists to size. A cache-served `get` lands in the first
# bucket by construction, which is the point — that is the latency a TTL buys.
_CATALOG_DURATION_BUCKETS = (
    0.001,
    0.005,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    20.0,
    30.0,
    60.0,
)
CATALOG_DURATION_VIEW = View(
    instrument_name="catalog_*_duration_seconds",
    aggregation=ExplicitBucketHistogramAggregation(_CATALOG_DURATION_BUCKETS),
)


def configure_metrics(config: AppConfig) -> MeterProvider:
    """Install the OTel→Prometheus reader so domain instruments land on the default REGISTRY.

    HTTP `/metrics` itself is served by `unique_mcp.monitoring.setup_ops` (via
    `unique_toolkit.monitoring.get_metrics`), which reads that same registry.
    """
    global _provider
    if _provider is not None:
        return _provider
    resource = Resource.create({SERVICE_NAME: "backstop-mcp", SERVICE_VERSION: config.version})
    reader = PrometheusMetricReader()
    provider = MeterProvider(
        resource=resource, metric_readers=[reader], views=[CATALOG_DURATION_VIEW]
    )
    metrics.set_meter_provider(provider)
    _provider = provider
    return provider


# Instruments are created at import time against the OTel API, not the SDK. Before
# `configure_metrics` runs, `get_meter` hands back a proxy that buffers instrument creation
# and rebinds to the real provider once one is set — so import order doesn't matter and
# nothing needs a lazy accessor.
_meter = metrics.get_meter("backstop_mcp")

BACKSTOP_REQUESTS = _meter.create_counter(
    "backstop_requests_total",
    description="Upstream Backstop API requests, by method/outcome.",
)
BACKSTOP_REQUEST_DURATION = _meter.create_histogram(
    "backstop_request_duration_seconds",
    unit="s",
    description="Wall-clock duration of a single upstream Backstop API request.",
)
BACKSTOP_RATE_LIMITED = _meter.create_counter(
    "backstop_rate_limited_total",
    description="Backstop 429 responses, by classified limit kind and whether we retried.",
)
BACKSTOP_CONCURRENCY_WAIT = _meter.create_histogram(
    "backstop_concurrency_wait_seconds",
    unit="s",
    description="Time spent waiting on the per-user concurrency gate before a request ran.",
)
CUSTOM_FIELD_SCHEMA_LOADS = _meter.create_counter(
    "custom_field_schema_loads_total",
    description="Custom-field schema loads, by source (backstop refresh, stale reuse).",
)
# The demand half of the pair. Every `CachedCatalog.get` records here exactly once, whatever
# answered it, so `_count` is the question "how many walks would there be with no cache at all?"
# — and `served` says what each caller actually got: its own walk (`backstop`), another caller's
# in-flight walk (`coalesced`), a TTL hit (`cache`), the previous catalog after a failed refresh
# (`stale`), or nothing (`error` / `cancelled`). The duration is caller-visible latency, lock and
# coalescing wait included, which is what a tool call actually pays.
CATALOG_GET_DURATION = _meter.create_histogram(
    "catalog_get_duration_seconds",
    unit="s",
    description=(
        "Wall-clock duration of one `CachedCatalog.get`, by catalog and what served it. "
        "`_count` is total demand — the walks there would be with no cache and no coalescing."
    ),
)
# The walk half. `catalog_get_duration_seconds_count - catalog_fetch_duration_seconds_count` is
# the requests already avoided; splitting the former by `served` says which mechanism avoided
# them. Buckets for both come from `CATALOG_DURATION_VIEW`.
CATALOG_FETCH_DURATION = _meter.create_histogram(
    "catalog_fetch_duration_seconds",
    unit="s",
    description=(
        "Wall-clock duration of one `CachedCatalog` walk, by catalog and outcome. `_count` is "
        "how often Backstop was actually walked, however many callers were served from it."
    ),
)
