from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource

from with_intelligence_mcp.config import AppConfig

_provider: MeterProvider | None = None


def configure_metrics(config: AppConfig) -> MeterProvider:
    """Install the OTel→Prometheus reader. HTTP `/metrics` itself is served by `setup_ops`."""
    global _provider
    if _provider is not None:
        return _provider
    resource = Resource.create(
        {SERVICE_NAME: "with-intelligence-mcp", SERVICE_VERSION: config.version}
    )
    provider = MeterProvider(resource=resource, metric_readers=[PrometheusMetricReader()])
    metrics.set_meter_provider(provider)
    _provider = provider
    return provider


# Created against the OTel API, not the SDK: before `configure_metrics` runs, `get_meter`
# returns a proxy that rebinds once a provider is set, so import order does not matter.
_meter = metrics.get_meter("with_intelligence_mcp")

UPSTREAM_REQUESTS = _meter.create_counter(
    "with_intelligence_requests_total",
    description="Upstream With Intelligence API requests, by method/outcome.",
)
UPSTREAM_REQUEST_DURATION = _meter.create_histogram(
    "with_intelligence_request_duration_seconds",
    unit="s",
    description="Wall-clock duration of a single upstream With Intelligence API request.",
)
UPSTREAM_RATE_LIMITED = _meter.create_counter(
    "with_intelligence_rate_limited_total",
    description="With Intelligence 429 responses, and whether we retried.",
)
UPSTREAM_CONCURRENCY_WAIT = _meter.create_histogram(
    "with_intelligence_concurrency_wait_seconds",
    unit="s",
    description="Time spent waiting on the per-user concurrency gate before a request ran.",
)
