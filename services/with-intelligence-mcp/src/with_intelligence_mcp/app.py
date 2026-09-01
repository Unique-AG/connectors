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

from with_intelligence_mcp.dependencies import get_app_config, get_engine
from with_intelligence_mcp.logging import configure_logging
from with_intelligence_mcp.metrics import configure_metrics
from with_intelligence_mcp.server.instructions import INSTRUCTIONS
from with_intelligence_mcp.server.tools import TOOLS
from with_intelligence_mcp.teardown import close_singletons

logger = logging.getLogger(__name__)


def create_app() -> Starlette:
    """Assemble the ASGI app.

    Logging, metrics, FastMCP, TOOLS, setup_ops, /ready, middleware, lifespan
    `close_singletons()`.

    No authorization server yet: until the auth feature lands, `FastMCP` is built without an
    auth provider and the login routes it will own do not exist. Every other piece of the
    composition root is in place, so adding it is one wiring change rather than a new file.
    """
    config = get_app_config()

    configure_logging(config)
    configure_metrics(config)

    engine = get_engine()

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncGenerator[None, None]:
        try:
            yield
        finally:
            await close_singletons()

    mcp = FastMCP(
        "With Intelligence MCP",
        version=config.version,
        lifespan=lifespan,
        instructions=INSTRUCTIONS,
    )
    for fn in TOOLS:
        mcp.add_tool(fn)

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

    Postgres is a hard dependency — OAuth token validation will read it on every request — so an
    unreachable database means not ready.
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
