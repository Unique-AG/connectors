from importlib.metadata import version

from fastmcp import FastMCP
from starlette.middleware import Middleware
from unique_mcp.logging import configure_logging
from unique_mcp.monitoring import setup_ops
from unique_toolkit.monitoring import configure_tracing

from mcp_runtime.settings import LoggingSettings


def init_telemetry(service_name: str, settings: LoggingSettings) -> None:
    """Tracing reads its settings (OTEL_*) from the environment."""
    configure_tracing(service_name=service_name, service_version=version(service_name))
    configure_logging(level=settings.log_level)


def instrument(mcp: FastMCP) -> Middleware:
    """Mount /probe, /health and /metrics, and return the app's HTTP metrics middleware.

    Every MCP call is counted, timed and logged as well.
    """
    return setup_ops(mcp)
