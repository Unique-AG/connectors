from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource

from backstop_mcp.config import AppConfig

_provider: MeterProvider | None = None


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
    provider = MeterProvider(resource=resource, metric_readers=[reader])
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
    description="Custom-field schema loads, by source (backstop refresh, snapshot, stale reuse).",
)
