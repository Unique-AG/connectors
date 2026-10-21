from importlib.metadata import version

from fastmcp import FastMCP
from mcp_configs import LoggingSettings
from starlette.middleware import Middleware
from unique_mcp.logging import configure_logging
from unique_mcp.monitoring import setup_ops
from unique_toolkit.monitoring import configure_tracing

SERVICE_NAME = "mcp-skeleton"


def init_telemetry(settings: LoggingSettings) -> None:
    """Runs before anything logs. Tracing reads its settings (OTEL_*) from the environment."""
    configure_tracing(service_name=SERVICE_NAME, service_version=version(SERVICE_NAME))
    configure_logging(level=settings.log_level)


def instrument(mcp: FastMCP) -> Middleware:
    """Mounts /probe, /health and /metrics, and returns the app's HTTP metrics middleware.

    Every tool, resource and prompt call is counted, timed and logged as well.
    """
    return setup_ops(mcp)
