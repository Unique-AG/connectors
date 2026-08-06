import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from unique_mcp.monitoring import setup_ops

from backstop_mcp.config import AppConfig, DatabaseConfig
from backstop_mcp.db import create_engine
from backstop_mcp.logging import configure_logging
from backstop_mcp.metrics import configure_metrics

logger = logging.getLogger(__name__)


def create_app(
    config: AppConfig | None = None,
    database_config: DatabaseConfig | None = None,
) -> Starlette:
    """The composition root.

    Every config object and every long-lived collaborator is built exactly once here and then
    injected. Nothing downstream re-reads the environment. This is scaffolding only: no OAuth,
    no Backstop client, and no tools yet — those land in later PRs, wired in here the same way.
    """
    config = config or AppConfig()
    database_config = database_config or DatabaseConfig()

    configure_logging(config)
    configure_metrics(config)

    engine = create_engine(database_config)

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncGenerator[None, None]:
        try:
            yield
        finally:
            await engine.dispose()

    mcp = FastMCP(
        "Backstop MCP",
        version=config.version,
        middleware=[],
        lifespan=lifespan,
    )

    # Mounts /probe, /health, /metrics and returns HTTP request-metrics middleware.
    ops_middleware = setup_ops(mcp)

    @mcp.custom_route("/ready", methods=["GET"])
    async def ready(_request: Request) -> JSONResponse:
        """Postgres readiness — stock `setup_ops` `/probe` is process-up only."""
        return await _ready_response(engine)

    return mcp.http_app(
        middleware=[
            Middleware(OpenTelemetryMiddleware),
            ops_middleware,
        ]
    )


async def _ready_response(engine: AsyncEngine) -> JSONResponse:
    """Readiness, reporting the checks it actually ran.

    Postgres is a hard dependency, so an unreachable database means not ready.
    """
    database_ok = True
    try:
        async with engine.connect() as connection:
            _ = await connection.execute(text("SELECT 1"))
    except Exception:
        database_ok = False
        logger.warning("ready.database_unreachable", exc_info=True)

    checks = {"database": database_ok}
    return JSONResponse(
        {"status": "healthy" if database_ok else "unhealthy", "checks": checks},
        status_code=200 if database_ok else 503,
    )
