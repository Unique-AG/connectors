# mcp-scaffold-version: 0.0.1, timestamp: 2026-10-21T12:09:32+00:00

from importlib.metadata import version

from fastmcp import FastMCP
from mcp_configs import LoggingSettings
from mcp_configs import TracingSettings
from mcp_observability import configure_logging
from mcp_observability import configure_tracing
from mcp_observability import setup_ops
from starlette.middleware import Middleware

SERVICE_NAME = "architecture-demo-mcp"


def init_telemetry(settings: LoggingSettings) -> None:
    """Runs before anything logs. Tracing reads its settings (OTEL_*) from the environment."""
    configure_tracing(
        TracingSettings(), service_name=SERVICE_NAME, service_version=version(SERVICE_NAME)
    )
    configure_logging(level=settings.log_level)


def instrument(mcp: FastMCP) -> Middleware:
    """Mounts /probe, /health and /metrics, and returns the app's HTTP metrics middleware.

    Every tool, resource and prompt call is counted, timed and logged as well.
    """
    return setup_ops(mcp)
