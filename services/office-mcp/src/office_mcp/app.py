import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Protocol, cast

import asyncpg
from fastmcp import FastMCP
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from opentelemetry.metrics import NoOpMeterProvider
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from unique_mcp.monitoring import setup_ops
from unique_toolkit.monitoring import configure_tracing

from office_mcp.config import AppConfig, DatabaseConfig
from office_mcp.logging import configure_logging
from office_mcp.metrics import configure_metrics

logger = logging.getLogger(__name__)


# asyncpg has no type stubs; narrowed here for type checking the readiness path.
class _Connection(Protocol):
    async def fetchval(self, query: str, /) -> object: ...
    async def close(self) -> None: ...


_connect = cast("Callable[[str], Awaitable[_Connection]]", asyncpg.connect)


def create_app(
    config: AppConfig | None = None,
    database_config: DatabaseConfig | None = None,
) -> Starlette:
    """Build the app.

    All config objects and long-lived collaborators are built here once, then injected.
    Nothing downstream re-reads the environment.
    Scaffolding only: no OAuth, no Graph client, no tools yet.
    """
    config = config or AppConfig()
    database_config = database_config or DatabaseConfig()

    configure_logging(config)
    configure_metrics(config)
    # Here, beside configure_metrics, rather than in main.py where kb-mcp puts it: everything that
    # depends on a tracer provider — OpenTelemetryMiddleware, the two middlewares below, FastMCP's
    # own spans — is assembled in this function, and main.py is not the only caller of it. Installed
    # from main.py, `create_app()` would compose an instrumented app against a provider only the CLI
    # entrypoint had installed. kb-mcp's main() *is* its composition root, so its placement is the
    # same decision, not a different one.
    # The version is passed rather than left to TracingSettings, which would read the bare VERSION
    # env var: config.version is this service's one source of truth for it, as in metrics.py.
    # Self-disabling when no OTEL_* variable is set, so a test process stays untraced.
    configure_tracing(service_name="office-mcp", service_version=config.version)

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncGenerator[None, None]:
        yield

    mcp = FastMCP(
        "Office MCP",
        version=config.version,
        middleware=[],
        lifespan=lifespan,
    )

    # Mounts /probe, /health, /metrics and returns HTTP request-metrics middleware.
    ops_middleware = setup_ops(mcp)

    @mcp.custom_route("/ready", methods=["GET"])
    async def ready(_request: Request) -> JSONResponse:
        """Check if Postgres is reachable. The `/probe` route checks process up only."""
        return await _ready_response(database_config.driver_dsn)

    return mcp.http_app(
        middleware=[
            # A no-op meter provider on purpose. Left to the global one, this middleware's own
            # instruments resolve against the provider metrics.py aims at the toolkit registry, and
            # /metrics then serves two histograms for one latency: http_server_duration_milliseconds
            # beside unique_toolkit's python_http_request_duration_seconds. The toolkit series is
            # the one the house dashboards read, and its python_http_requests_in_progress covers
            # what http_server_active_requests would have said, so the toolkit series stays the only
            # one. Spans are unaffected — the tracer provider is untouched.
            Middleware(OpenTelemetryMiddleware, meter_provider=NoOpMeterProvider()),
            ops_middleware,
        ]
    )


async def _ready_response(dsn: str) -> JSONResponse:
    """Check readiness and report results. Open one connection per probe to match production path.

    Trap: No engine and no pool. A probe that uses a different connection path than
    the code doing real work can report healthy while that work fails.
    """
    database_ok = True
    try:
        connection = await _connect(dsn)
        try:
            _ = await connection.fetchval("SELECT 1")
        finally:
            await connection.close()
    except Exception:
        database_ok = False
        logger.warning("ready.database_unreachable", exc_info=True)

    checks = {"database": database_ok}
    return JSONResponse(
        {"status": "healthy" if database_ok else "unhealthy", "checks": checks},
        status_code=200 if database_ok else 503,
    )
