from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from unique_toolkit.monitoring import REGISTRY as _TOOLKIT_REGISTRY

from office_mcp.config import AppConfig

_provider: MeterProvider | None = None


def configure_metrics(config: AppConfig) -> MeterProvider:
    """Install OTel→Prometheus reader to route domain instruments to the toolkit registry."""
    global _provider
    if _provider is not None:
        return _provider
    resource = Resource.create({SERVICE_NAME: "office-mcp", SERVICE_VERSION: config.version})
    reader = PrometheusMetricReader(registry=_TOOLKIT_REGISTRY)
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)
    _provider = provider
    return provider


# Domain instruments declared here at import time. OTel proxy buffers creation
# until configure_metrics runs.
_meter = metrics.get_meter("office_mcp")
