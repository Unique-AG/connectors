from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource

from office_mcp.config import AppConfig

_provider: MeterProvider | None = None


def configure_metrics(config: AppConfig) -> MeterProvider:
    """Install the OTel→Prometheus reader so domain instruments land on the default REGISTRY.

    HTTP `/metrics` itself is served by `unique_mcp.monitoring.setup_ops` (via
    `unique_toolkit.monitoring.get_metrics`), which reads that same registry.
    """
    global _provider
    if _provider is not None:
        return _provider
    resource = Resource.create({SERVICE_NAME: "office-mcp", SERVICE_VERSION: config.version})
    reader = PrometheusMetricReader()
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)
    _provider = provider
    return provider


# Domain instruments are declared here, at import time, against the OTel API rather than the SDK.
# Before `configure_metrics` runs, `get_meter` hands back a proxy that buffers instrument creation
# and rebinds to the real provider once one is set — so import order doesn't matter and nothing
# needs a lazy accessor. There are none yet: the first ones land with the Microsoft Graph client.
_meter = metrics.get_meter("office_mcp")
