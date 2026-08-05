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

from backstop_mcp.backstop_client.factory import create_backstop_client_factory
from backstop_mcp.config import (
    AppConfig,
    AuthConfig,
    BackstopConfig,
    DatabaseConfig,
    EncryptionConfig,
)
from backstop_mcp.db.engine import create_engine, create_session_factory
from backstop_mcp.features.auth.cleanup import cleanup_lifespan
from backstop_mcp.features.auth.context import BackstopAuthContext
from backstop_mcp.features.auth.crypto import load_key
from backstop_mcp.features.auth.provider import BackstopOAuthProvider
from backstop_mcp.features.auth.throttle import ThrottleConfig
from backstop_mcp.features.custom_fields import create_custom_fields_service
from backstop_mcp.features.custom_fields.warmup import warmup_lifespan
from backstop_mcp.logging import configure_logging, get_logger
from backstop_mcp.metrics import configure_metrics, metrics_endpoint
from backstop_mcp.server.middleware.custom_field_glossary import CustomFieldGlossaryMiddleware
from backstop_mcp.server.middleware.trace_context import TraceContextMiddleware
from backstop_mcp.server.runtime import Services, configure_services, reset_services
from backstop_mcp.server.tools.registry import TOOL_SPECS, glossary_entities_by_tool_name

logger = get_logger(__name__)


def create_app(
    config: AppConfig | None = None,
    backstop_config: BackstopConfig | None = None,
    database_config: DatabaseConfig | None = None,
    encryption_config: EncryptionConfig | None = None,
    auth_config: AuthConfig | None = None,
) -> Starlette:
    """The composition root.

    Every config object and every long-lived collaborator is built exactly once here and then
    injected. Nothing downstream re-reads the environment — in particular `BackstopConfig` is
    owned by `BackstopClientFactory`, so the tuning knobs a deployment sets are the ones every
    request actually uses.
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
    backstop_clients = create_backstop_client_factory(backstop_config)
    auth_provider = BackstopOAuthProvider(
        base_url=config.public_base_url,
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
            revoke_tokens_for_subject=auth_provider.revoke_token_family_for_subject,
        )
    )

    custom_fields_service = create_custom_fields_service(
        session_factory=session_factory,
        base_url=backstop_config.base_url,
        overrides=backstop_config.custom_field_overrides,
        ttl_minutes=backstop_config.custom_field_schema_ttl_minutes,
    )
    configure_services(Services(backstop=backstop_clients, custom_fields=custom_fields_service))

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncGenerator[None, None]:
        async with (
            warmup_lifespan(custom_fields_service, backstop_clients),
            cleanup_lifespan(session_factory, auth_config),
        ):
            try:
                yield
            finally:
                await reset_services()
                await engine.dispose()

    mcp = FastMCP(
        "Backstop MCP",
        version=config.version,
        auth=auth_provider,
        middleware=[
            CustomFieldGlossaryMiddleware(
                custom_fields_service,
                # A bound method, safe to capture: it reads the factory's auth context at call
                # time, and `attach_auth` above has already run.
                client_for_caller=backstop_clients.for_current_caller,
                glossary_entities=glossary_entities_by_tool_name(),
            )
        ],
        lifespan=lifespan,
    )
    for spec in TOOL_SPECS:
        mcp.tool(spec.fn)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @mcp.custom_route("/probe", methods=["GET"])
    async def probe(_request: Request) -> JSONResponse:
        return await _probe_response(
            engine, custom_fields_schema_loaded=bool(custom_fields_service.has_definitions)
        )

    @mcp.custom_route("/metrics", methods=["GET"])
    async def metrics_route(request: Request) -> Response:
        return await metrics_endpoint(request)

    @mcp.custom_route(auth_provider.login_path, methods=["GET"])
    async def login_get(request: Request) -> Response:
        return await auth_provider.handle_login_get(request)

    @mcp.custom_route(auth_provider.login_path, methods=["POST"])
    async def login_post(request: Request) -> Response:
        return await auth_provider.handle_login_post(request)

    return mcp.http_app(
        middleware=[
            Middleware(OpenTelemetryMiddleware),
            Middleware(TraceContextMiddleware),
        ]
    )


async def _probe_response(
    engine: AsyncEngine, *, custom_fields_schema_loaded: bool
) -> JSONResponse:
    """Readiness, reporting the checks it actually ran.

    Postgres is a hard dependency — OAuth token validation reads it on every request — so an
    unreachable database means not ready. The custom-field schema is reported but never gates
    readiness: it fills lazily by design, and tools degrade to `resolve_custom_field` without it.
    """
    database_ok = True
    try:
        async with engine.connect() as connection:
            _ = await connection.execute(text("SELECT 1"))
    except Exception:
        database_ok = False
        logger.warning("probe.database_unreachable", exc_info=True)

    checks = {"database": database_ok, "custom_field_schema": custom_fields_schema_loaded}
    return JSONResponse(
        {"status": "healthy" if database_ok else "unhealthy", "checks": checks},
        status_code=200 if database_ok else 503,
    )
