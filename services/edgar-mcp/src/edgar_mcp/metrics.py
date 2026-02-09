from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from edgar_mcp.config import AppConfig


def configure_metrics(app_config: AppConfig) -> MeterProvider:
    """Configure OpenTelemetry metrics with Prometheus exporter."""
    resource = Resource.create(
        {
            SERVICE_NAME: "edgar-mcp",
            SERVICE_VERSION: app_config.version,
        }
    )

    reader = PrometheusMetricReader()
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)

    return provider


def create_metrics_app() -> Starlette:
    """Create ASGI app that serves Prometheus metrics."""

    async def metrics_endpoint(_request: Request) -> Response:
        data = generate_latest(REGISTRY)
        return Response(data, media_type=CONTENT_TYPE_LATEST)

    return Starlette(routes=[Route("/", metrics_endpoint)])


def get_meter(name: str) -> metrics.Meter:
    """Get a meter for creating metrics."""
    return metrics.get_meter(name)
