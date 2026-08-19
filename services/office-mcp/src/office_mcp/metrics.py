from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from unique_toolkit.monitoring import REGISTRY as _TOOLKIT_REGISTRY

from office_mcp.config import AppConfig
from office_mcp.graph_client import GRAPH_PAGES_SCANNED, GRAPH_REQUEST_DURATION_SECONDS

_provider: MeterProvider | None = None

# Two histograms whose default buckets would answer the wrong question, corrected here rather than
# where they are declared: a bucket layout is an aggregation, an aggregation is the provider's, and
# a view matches on the instrument's name — so this needs nothing from the module that records it.
#
# The OpenTelemetry default layout runs 0, 5, 10, 25 … 10000, which is minutes-shaped. A Graph call
# is capped at `GraphSettings.request_timeout_seconds`, so every honest observation would land in
# the first bucket and every quantile would read the same.
_VIEWS = (
    View(
        instrument_name=GRAPH_REQUEST_DURATION_SECONDS,
        # `prometheus_client`'s own defaults, which is what unique_toolkit's
        # `python_http_request_duration_seconds` uses, plus two above them. A dashboard that puts
        # inbound MCP latency beside outbound Graph latency can then read one against the other,
        # and the two extra buckets are where a Retry-After wait and a timed-out call land — the
        # slow tail is the whole reason to look.
        aggregation=ExplicitBucketHistogramAggregation(
            (0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0, 30.0)
        ),
    ),
    View(
        instrument_name=GRAPH_PAGES_SCANNED,
        # Nearly every walk reads one page, so the low end is spelled out one page at a time. A walk
        # that gives up on a collection Graph will not end lands just past 10 (`MAX_EMPTY_PAGES`),
        # and only the item scan cap bounds anything above that.
        aggregation=ExplicitBucketHistogramAggregation((1, 2, 3, 5, 10, 25, 50, 100, 250, 1000)),
    ),
)


def configure_metrics(config: AppConfig) -> MeterProvider:
    """Install OTel→Prometheus reader to route domain instruments to the toolkit registry.

    Trap: `/metrics` reads `unique_toolkit.monitoring.REGISTRY`, not `prometheus_client`'s
    default registry. Point the reader at it explicitly, or metrics never appear in a scrape.
    """
    global _provider
    if _provider is not None:
        return _provider
    resource = Resource.create({SERVICE_NAME: "office-mcp", SERVICE_VERSION: config.version})
    reader = PrometheusMetricReader(registry=_TOOLKIT_REGISTRY)
    provider = MeterProvider(resource=resource, metric_readers=[reader], views=list(_VIEWS))
    metrics.set_meter_provider(provider)
    _provider = provider
    return provider


# Domain instruments declared here at import time. OTel proxy buffers creation
# until configure_metrics runs, so import order does not matter here.
#
# The `graph_*` family is the exception and cannot move here: it is recorded inside
# `graph_client/`, which imports nothing of this application, so its instruments are declared in
# `graph_client/observability.py` — on this same meter name, so they share this scope. What stays
# here is their aggregation, in `_VIEWS` above. Look there for `graph_requests_total`,
# `graph_request_duration_seconds`, `graph_throttled_total` and `graph_pages_scanned`.
_meter = metrics.get_meter("office_mcp")
