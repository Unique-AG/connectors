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
from starlette.responses import JSONResponse, Response
from unique_mcp.monitoring import setup_ops

from with_intelligence_mcp.dependencies import (
    get_app_config,
    get_auth_config,
    get_auth_provider,
    get_engine,
    get_session_factory,
)
from with_intelligence_mcp.features.auth import cleanup_lifespan
from with_intelligence_mcp.logging import configure_logging
from with_intelligence_mcp.metrics import configure_metrics
from with_intelligence_mcp.server.instructions import INSTRUCTIONS
from with_intelligence_mcp.server.tools import TOOLS
from with_intelligence_mcp.teardown import close_singletons

logger = logging.getLogger(__name__)


def create_app() -> Starlette:
    """Assemble the ASGI app: logging, metrics, FastMCP, TOOLS, setup_ops, /ready, /login,
    lifespan `close_singletons()`."""
    config = get_app_config()
    auth_config = get_auth_config()

    configure_logging(config)
    configure_metrics(config)

    engine = get_engine()
    session_factory = get_session_factory()
    auth_provider = get_auth_provider()

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncGenerator[None, None]:
        # Stop the auth sweep before disposing the engine — otherwise `cleanup_lifespan`'s
        # cancel/await runs after the pool is already closed.
        try:
            async with cleanup_lifespan(session_factory, auth_config):
                yield
        finally:
            await close_singletons()

    mcp = FastMCP(
        "With Intelligence MCP",
        version=config.version,
        auth=auth_provider,
        lifespan=lifespan,
        instructions=INSTRUCTIONS,
    )
    for fn in TOOLS:
        mcp.add_tool(fn)

    # Mounts /probe, /health, /metrics and returns HTTP request-metrics middleware.
    ops_middleware = setup_ops(mcp)

    @mcp.custom_route("/ready", methods=["GET"])
    async def ready(_request: Request) -> JSONResponse:
        return await _ready_response(engine)

    @mcp.custom_route(auth_provider.login_path, methods=["GET"])
    async def login_get(request: Request) -> Response:
        return await auth_provider.handle_login_get(request)

    @mcp.custom_route(auth_provider.login_path, methods=["POST"])
    async def login_post(request: Request) -> Response:
        return await auth_provider.handle_login_post(request)

    return mcp.http_app(middleware=[Middleware(OpenTelemetryMiddleware), ops_middleware])


async def _ready_response(engine: AsyncEngine) -> JSONResponse:
    """Postgres readiness — stock `setup_ops` `/probe` is process-up only.

    A hard dependency now: OAuth token validation reads the database on every request.
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
