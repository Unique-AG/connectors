import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from mcp.server.transport_security import (
    DEFAULT_MAX_REQUEST_BODY_SIZE,
    RequestBodyLimitMiddleware,
)
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from opentelemetry.metrics import NoOpMeterProvider
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from unique_mcp.monitoring import setup_ops
from unique_toolkit.monitoring import configure_tracing

from backstop_mcp.backstop_client import BackstopCredentialSecret
from backstop_mcp.dependencies import (
    get_app_config,
    get_auth_config,
    get_auth_provider,
    get_backstop_client_factory,
    get_encryption_key,
    get_engine,
    get_session_factory,
    get_tenant_guidance_config,
)
from backstop_mcp.features.auth import cleanup_lifespan
from backstop_mcp.features.system_users import find_system_user_by_user_name
from backstop_mcp.logging import configure_logging
from backstop_mcp.metrics import configure_metrics
from backstop_mcp.observability import install_caller_failure_redaction
from backstop_mcp.server.instructions import INSTRUCTIONS
from backstop_mcp.server.session_revoked import SessionRevokedToUnauthorizedMiddleware
from backstop_mcp.server.tenant_guidance import (
    check_guidance_targets,
    compose_instructions,
    with_tool_guidance,
)
from backstop_mcp.server.tool_call_observability import ToolCallObservabilityMiddleware
from backstop_mcp.server.tools import TOOLS
from backstop_mcp.teardown import close_singletons
from backstop_mcp.utils import configure_identifiable_values

logger = logging.getLogger(__name__)

# Above this, the readiness handler answers 503 itself. The chart probe timeout sits higher.
_READY_CHECK_TIMEOUT_SECONDS = 2.0


def create_app() -> Starlette:
    """Build the ASGI app: logging, metrics, the MCP server, its tools, and this
    deployment's tenant guidance, login, and readiness.
    """
    config = get_app_config()
    auth_config = get_auth_config()

    configure_logging(config)
    configure_identifiable_values(
        policy=config.logs_diagnostics_data_policy,
        log_level=config.log_level.value,
        encryption_key=get_encryption_key(),
    )
    configure_metrics(config)
    # Before FastMCP is built. A no-op when no OTEL_* variable is set, so tests stay untraced.
    configure_tracing(service_name="backstop-mcp", service_version=config.version)
    install_caller_failure_redaction()

    engine = get_engine()
    session_factory = get_session_factory()
    auth_provider = get_auth_provider()
    auth_provider.attach_resolve_system_user(_resolve_system_user_for_login)

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncGenerator[None]:
        # Stop background tasks (auth sweep) before disposing the engine — otherwise
        # `cleanup_lifespan`'s cancel/await runs after the pool is already closed.
        try:
            async with cleanup_lifespan(session_factory, auth_config):
                yield
        finally:
            await close_singletons()

    guidance = get_tenant_guidance_config().tenant_guidance
    readiness = _ReadinessLog()
    mcp = FastMCP(
        "Backstop MCP",
        version=config.version,
        auth=auth_provider,
        lifespan=lifespan,
        instructions=compose_instructions(INSTRUCTIONS, guidance),
        # Outermost MCP middleware. `setup_ops` appends metrics inside it.
        middleware=[ToolCallObservabilityMiddleware()],
    )
    registered = tuple(mcp.add_tool(fn) for fn in TOOLS)
    check_guidance_targets(guidance, registered)
    if guidance.tools:
        for tool in registered:
            mcp.local_provider.remove_tool(tool.name)
        for tool in registered:
            entry = guidance.tools.get(tool.name)
            mcp.add_tool(tool if entry is None else with_tool_guidance(tool, entry))
    logger.info(
        "tenant_guidance.applied",
        extra={
            "server_instructions_chars": len(guidance.server_instructions or ""),
            "tools": sorted(guidance.tools),
        },
    )

    # Mounts /probe, /health, /metrics and returns HTTP request-metrics middleware.
    ops_middleware = setup_ops(mcp)

    @mcp.custom_route("/ready", methods=["GET"])
    async def ready(_request: Request) -> JSONResponse:
        """Postgres readiness — stock `setup_ops` `/probe` is process-up only."""
        return await _ready_response(engine, readiness)

    @mcp.custom_route(auth_provider.login_path, methods=["GET"])
    async def login_get(request: Request) -> Response:
        return await auth_provider.handle_login_get(request)

    @mcp.custom_route(auth_provider.login_path, methods=["POST"])
    async def login_post(request: Request) -> Response:
        return await auth_provider.handle_login_post(request)

    return mcp.http_app(
        middleware=[
            # Same cap as StreamableHTTPSessionManager; FastMCP has no knob, so matching
            # avoids two limits that can drift. Also bounds the unauthenticated login POST.
            Middleware(RequestBodyLimitMiddleware, max_body_size=DEFAULT_MAX_REQUEST_BODY_SIZE),
            Middleware(
                OpenTelemetryMiddleware,
                excluded_urls="/health$,/probe$,/ready$,/metrics$",
                exclude_spans=["receive", "send"],
                # The global meter is what `/metrics` scrapes. This middleware's histogram would
                # duplicate unique_toolkit's HTTP one, in different units.
                meter_provider=NoOpMeterProvider(),
            ),
            ops_middleware,
            # Innermost: Starlette wraps last-listed first, so the rewritten 401 is what
            # request-metrics / OTel see. First-listed would rewrite on the raw send after they
            # already recorded the JSON-RPC 200.
            Middleware(SessionRevokedToUnauthorizedMiddleware),
        ]
    )


async def _resolve_system_user_for_login(
    username: str, api_token: str
) -> tuple[str, dict[str, object]] | None:
    credential = BackstopCredentialSecret(username=username, api_token=SecretStr(api_token))
    client = get_backstop_client_factory().for_credential(credential)
    user = await find_system_user_by_user_name(client, username)
    if user is None:
        return None
    return user.id, user.model_dump(mode="json")


class _ReadinessLog:
    """One line when readiness changes, not one line per probe."""

    def __init__(self) -> None:
        self._healthy: bool | None = None

    def observe(self, *, healthy: bool, exc: BaseException | None) -> None:
        previous = self._healthy
        self._healthy = healthy
        if previous is None:
            if not healthy:
                logger.warning("ready.database_unreachable", exc_info=exc)
            return
        if previous == healthy:
            logger.debug("ready.database_unchanged", extra={"healthy": healthy})
            return
        if healthy:
            logger.info("ready.database_recovered")
            return
        logger.warning("ready.database_unreachable", exc_info=exc)


async def _ready_response(engine: AsyncEngine, readiness: _ReadinessLog) -> JSONResponse:
    """Readiness, reporting the checks it actually ran.

    Postgres is a hard dependency — OAuth token validation reads it on every request — so an
    unreachable database means not ready. The check is bounded so a hung connection cannot
    hold the probe past the chart's timeout.
    """
    database_ok = True
    error: BaseException | None = None
    try:
        async with asyncio.timeout(_READY_CHECK_TIMEOUT_SECONDS):
            async with engine.connect() as connection:
                _ = await connection.execute(text("SELECT 1"))
    except Exception as exc:
        database_ok = False
        error = exc
    readiness.observe(healthy=database_ok, exc=error)

    checks = {"database": database_ok}
    return JSONResponse(
        {"status": "healthy" if database_ok else "unhealthy", "checks": checks},
        status_code=200 if database_ok else 503,
    )
