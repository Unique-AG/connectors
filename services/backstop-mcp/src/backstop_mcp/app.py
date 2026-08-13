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

from backstop_mcp.backstop_client import (
    BackstopClientFactory,
    BackstopTransportSettings,
    RetrySettings,
)
from backstop_mcp.config import (
    AppConfig,
    AuthConfig,
    BackstopConfig,
    DatabaseConfig,
    EncryptionConfig,
)
from backstop_mcp.db import create_engine, create_session_factory
from backstop_mcp.features.auth import (
    BackstopAuthContext,
    BackstopOAuthProvider,
    ThrottleConfig,
    cleanup_lifespan,
    load_key,
)
from backstop_mcp.logging import configure_logging
from backstop_mcp.metrics import configure_metrics
from backstop_mcp.server.runtime import Services, configure_services, reset_services
from backstop_mcp.server.tools import TOOLS

logger = logging.getLogger(__name__)


def create_app(
    config: AppConfig | None = None,
    backstop_config: BackstopConfig | None = None,
    database_config: DatabaseConfig | None = None,
    encryption_config: EncryptionConfig | None = None,
    auth_config: AuthConfig | None = None,
) -> Starlette:
    """The composition root.

    Every config object and every long-lived collaborator is built exactly once here and then
    injected. Nothing downstream re-reads the environment, and no layer below this one sees a
    `config` type at all: each env-parsed shape is translated into the owning layer's own domain
    type here (`BackstopTransportSettings`, `RetrySettings`, `BackstopCredentialSecret`), so the
    tuning knobs a deployment sets are the ones every request actually uses.

    No tools yet: `TOOLS` is empty until `features/custom_fields` and `features/party_resolver`
    land, so the registration loop below is a no-op for now.
    """
    config = config or AppConfig()
    backstop_config = backstop_config or BackstopConfig()
    database_config = database_config or DatabaseConfig()
    encryption_config = encryption_config or EncryptionConfig()
    auth_config = auth_config or AuthConfig()

    configure_logging(config)
    configure_metrics(config)

    engine = create_engine(database_config)
    session_factory = create_session_factory(engine)
    encryption_key = load_key(encryption_config)

    # One factory, therefore one connection pool. The provider needs it (to verify credentials
    # at login) and it needs the provider (for the token-revocation hook inside the auth
    # context), so the cycle is closed with a single `attach_auth` step.
    backstop_clients = BackstopClientFactory(
        transport_settings(backstop_config), retry_settings(backstop_config)
    )
    auth_provider = BackstopOAuthProvider(
        base_url=config.issuer,
        secure_cookies=config.public_base_url.scheme == "https",
        session_factory=session_factory,
        encryption_key=encryption_key,
        backstop_clients=backstop_clients,
        throttle=ThrottleConfig(
            max_attempts=auth_config.login_max_attempts,
            window=auth_config.login_attempt_window,
        ),
    )
    backstop_clients.attach_auth(
        BackstopAuthContext(
            session_factory=session_factory,
            encryption_key=encryption_key,
            revoke_tokens_for_subject=auth_provider.revoke_all_tokens_for_subject,
        )
    )

    configure_services(Services(backstop=backstop_clients))

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncGenerator[None, None]:
        # Stop the auth sweep before disposing the engine — otherwise
        # `cleanup_lifespan`'s cancel/await runs after the pool is already closed.
        try:
            async with cleanup_lifespan(session_factory, auth_config):
                yield
        finally:
            await reset_services()
            await engine.dispose()

    mcp = FastMCP(
        "Backstop MCP",
        version=config.version,
        auth=auth_provider,
        middleware=[],
        lifespan=lifespan,
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


def transport_settings(config: BackstopConfig) -> BackstopTransportSettings:
    """Translate the env-parsed Backstop config into the transport's own settings type.

    Field-for-field, and deliberately explicit rather than derived by reflection: adding a knob
    to `BackstopConfig` that the transport should see is then a visible edit here.
    """
    return BackstopTransportSettings(
        base_url=config.base_url,
        default_timeout_seconds=config.default_timeout_seconds,
        reports_timeout_seconds=config.reports_timeout_seconds,
        max_concurrent_requests_per_user=config.max_concurrent_requests_per_user,
        default_page_size=config.default_page_size,
        report_page_size=config.report_page_size,
        page_limit_param=config.page_limit_param,
        page_offset_param=config.page_offset_param,
    )


def retry_settings(config: BackstopConfig) -> RetrySettings:
    return RetrySettings(
        max_attempts=config.max_retry_attempts, max_wait_ms=config.max_retry_wait_ms
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
