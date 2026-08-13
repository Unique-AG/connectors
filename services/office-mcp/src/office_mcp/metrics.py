from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from unique_toolkit.monitoring import REGISTRY as _TOOLKIT_REGISTRY

from office_mcp.config import AppConfig

_provider: MeterProvider | None = None


def configure_metrics(config: AppConfig) -> MeterProvider:
    """Install the OTel→Prometheus reader so domain instruments land where `/metrics` reads from.

    HTTP `/metrics` itself is served by `unique_mcp.monitoring.setup_ops` (via
    `unique_toolkit.monitoring.get_metrics`), which reads `unique_toolkit.monitoring.REGISTRY` —
    a `CollectorRegistry` distinct from `prometheus_client`'s module-level default. The reader
    is pointed at that same registry explicitly; otherwise its metrics land in the default
    registry and never appear in a scrape.
    """
    global _provider
    if _provider is not None:
        return _provider
    resource = Resource.create({SERVICE_NAME: "office-mcp", SERVICE_VERSION: config.version})
    reader = PrometheusMetricReader(registry=_TOOLKIT_REGISTRY)
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)
    _provider = provider
    return provider


# Domain instruments are declared here, at import time, against the OTel API rather than the SDK.
# Before `configure_metrics` runs, `get_meter` hands back a proxy that buffers instrument creation
# and rebinds to the real provider once one is set — so import order doesn't matter and nothing
# needs a lazy accessor. There are none yet: the first ones land with the Microsoft Graph client.
_meter = metrics.get_meter("office_mcp")
