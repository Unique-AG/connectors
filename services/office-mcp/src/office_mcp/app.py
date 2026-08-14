import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Protocol, cast

import asyncpg
from fastmcp import FastMCP
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from unique_mcp.monitoring import setup_ops

from office_mcp.config import AppConfig, DatabaseConfig
from office_mcp.logging import configure_logging
from office_mcp.metrics import configure_metrics

logger = logging.getLogger(__name__)


# asyncpg ships no type information, so this repo's strict checking sees every call on a
# connection as unknown. Narrowed once here — to just the two methods the probe uses — so the
# readiness path below is checked rather than silently untyped.
class _Connection(Protocol):
    async def fetchval(self, query: str, /) -> object: ...
    async def close(self) -> None: ...


_connect = cast("Callable[[str], Awaitable[_Connection]]", asyncpg.connect)


def create_app(
    config: AppConfig | None = None,
    database_config: DatabaseConfig | None = None,
) -> Starlette:
    """The composition root.

    Every config object and every long-lived collaborator is built exactly once here and then
    injected. Nothing downstream re-reads the environment. This is scaffolding only: no OAuth,
    no Microsoft Graph client, and no tools yet — those land in later PRs, wired in here the
    same way.
    """
    config = config or AppConfig()
    database_config = database_config or DatabaseConfig()

    configure_logging(config)
    configure_metrics(config)

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
        """Postgres readiness — stock `setup_ops` `/probe` is process-up only."""
        return await _ready_response(database_config.driver_dsn)

    return mcp.http_app(
        middleware=[
            Middleware(OpenTelemetryMiddleware),
            ops_middleware,
        ]
    )


async def _ready_response(dsn: str) -> JSONResponse:
    """Readiness, reporting the checks it actually ran.

    Postgres is a hard dependency, so an unreachable database means not ready.

    One short-lived connection on the same DSN every other caller uses, opened and closed per
    probe. No engine and no pool: a probe that connects by a different path than the code doing
    real work can report healthy while that work fails.
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
