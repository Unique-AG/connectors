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

from backstop_mcp.dependencies import (
    close_singletons,
    get_activity_history_config,
    get_app_config,
    get_auth_config,
    get_auth_provider,
    get_backstop_client_factory,
    get_backstop_config,
    get_engine,
    get_session_factory,
)
from backstop_mcp.features.activity_history import ActivityHistorySettings
from backstop_mcp.features.auth import cleanup_lifespan
from backstop_mcp.features.custom_fields import CustomFieldsService
from backstop_mcp.features.data_hygiene import EmploymentIndexFactory
from backstop_mcp.features.opportunities import OpportunityStagesService
from backstop_mcp.logging import configure_logging
from backstop_mcp.metrics import configure_metrics
from backstop_mcp.server.instructions import INSTRUCTIONS
from backstop_mcp.server.runtime import Services, configure_services, reset_services
from backstop_mcp.server.tools import TOOLS

logger = logging.getLogger(__name__)


def create_app() -> Starlette:
    """The composition root.

    Config and long-lived collaborators are resolved from the cached providers in
    `dependencies.py` — nothing here re-reads the environment. Feature services that still
    live on `runtime.Services` are built here and installed so tools via `runtime.py` keep
    working.
    """
    config = get_app_config()
    backstop_config = get_backstop_config()
    auth_config = get_auth_config()
    activity_history_config = get_activity_history_config()

    configure_logging(config)
    configure_metrics(config)

    engine = get_engine()
    session_factory = get_session_factory()
    backstop_clients = get_backstop_client_factory()
    auth_provider = get_auth_provider()

    custom_fields_service = CustomFieldsService.with_ttl_minutes(
        ttl_minutes=backstop_config.custom_field_schema_ttl_minutes,
    )
    opportunity_stages_service = OpportunityStagesService.with_ttl_minutes(
        ttl_minutes=backstop_config.opportunity_stage_ttl_minutes,
    )
    employment_index_factory = EmploymentIndexFactory.from_vocabulary(
        employment_type_ids=backstop_config.employment_relationship_type_ids,
        employment_type_markers=backstop_config.employment_relationship_type_markers,
        former_type_ids=backstop_config.former_employment_relationship_type_ids,
        former_type_markers=backstop_config.former_employment_relationship_type_markers,
    )
    configure_services(
        Services(
            backstop=backstop_clients,
            custom_fields=custom_fields_service,
            employment_index_factory=employment_index_factory,
            activity_history=ActivityHistorySettings(
                page_size=activity_history_config.page_size,
                gist_max_chars=activity_history_config.gist_chars,
            ),
            opportunity_stages=opportunity_stages_service,
        )
    )

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncGenerator[None, None]:
        # Stop background tasks (auth sweep) before disposing the engine — otherwise
        # `cleanup_lifespan`'s cancel/await runs after the pool is already closed.
        try:
            async with cleanup_lifespan(session_factory, auth_config):
                yield
        finally:
            await close_singletons()
            await reset_services()

    mcp = FastMCP(
        "Backstop MCP",
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
        """Postgres readiness — stock `setup_ops` `/probe` is process-up only."""
        return await _ready_response(engine)

    @mcp.custom_route(auth_provider.login_path, methods=["GET"])
    async def login_get(request: Request) -> Response:
        return await auth_provider.handle_login_get(request)

    @mcp.custom_route(auth_provider.login_path, methods=["POST"])
    async def login_post(request: Request) -> Response:
        return await auth_provider.handle_login_post(request)

    return mcp.http_app(
        middleware=[
            Middleware(OpenTelemetryMiddleware),
            ops_middleware,
        ]
    )


async def _ready_response(engine: AsyncEngine) -> JSONResponse:
    """Readiness, reporting the checks it actually ran.

    Postgres is a hard dependency — OAuth token validation reads it on every request — so an
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
