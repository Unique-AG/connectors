# mcp-scaffold-commit: 6474bb8667dc, timestamp: 2026-11-16T10:36:30+00:00

from importlib.metadata import version

from fastmcp import FastMCP
from mcp_configs import LoggingSettings
from mcp_configs import LogLevel
from mcp_configs import TracingSettings
from mcp_observability import configure_logging
from mcp_observability import configure_tracing
from mcp_observability import SecretRedaction
from mcp_observability import setup_ops
from starlette.middleware import Middleware

SERVICE_NAME = "kyckr-mcp"


def init_telemetry(settings: LoggingSettings, *, secrets: tuple[str, ...]) -> None:
    """Runs before anything logs. Tracing reads its settings (OTEL_*) from the environment.

    Every log line has `secrets`, the ones the deployment configures, replaced with `[Redacted]`.
    """
    configure_tracing(
        TracingSettings(),
        service_name=SERVICE_NAME,
        service_version=version(SERVICE_NAME),
        error_details_policy=settings.error_details_policy,
    )
    # httpx2 logs each request URL, search terms included, at INFO. LIBRARY_LOG_LEVELS wins.
    levels = {"httpx2": LogLevel.WARNING, **settings.library_log_levels}
    configure_logging(
        settings.model_copy(update={"library_log_levels": levels}),
        own_loggers=("kyckr_mcp",),
        redaction=SecretRedaction(secrets=secrets),
    )


def instrument(mcp: FastMCP) -> Middleware:
    """Mounts /probe, /health and /metrics, and returns the app's HTTP metrics middleware.

    Every tool, resource and prompt call is counted, timed and logged as well.
    """
    return setup_ops(mcp)
