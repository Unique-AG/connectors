from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest
from starlette.requests import Request
from starlette.responses import Response

from backstop_mcp.config import AppConfig

_provider: MeterProvider | None = None


def configure_metrics(config: AppConfig) -> MeterProvider:
    global _provider
    if _provider is not None:
        return _provider
    resource = Resource.create({SERVICE_NAME: "backstop-mcp", SERVICE_VERSION: config.version})
    reader = PrometheusMetricReader()
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)
    _provider = provider
    return provider


async def metrics_endpoint(_request: Request) -> Response:
    data = generate_latest(REGISTRY)
    return Response(data, media_type=CONTENT_TYPE_LATEST)


def get_meter(name: str) -> metrics.Meter:
    return metrics.get_meter(name)
