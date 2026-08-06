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
    BackstopCredentialSecret,
    BackstopTransportSettings,
    RetrySettings,
    create_backstop_client_factory,
)
from backstop_mcp.config import (
    AppConfig,
    AuthConfig,
    BackstopConfig,
    CustomFieldOverrideConfig,
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
from backstop_mcp.features.custom_fields import (
    FieldOverride,
    create_custom_fields_service,
    warmup_lifespan,
)
from backstop_mcp.features.data_hygiene import create_employment_index_factory
from backstop_mcp.logging import configure_logging
from backstop_mcp.metrics import configure_metrics
from backstop_mcp.server.middleware import CustomFieldGlossaryMiddleware
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
    type here (`BackstopTransportSettings`, `RetrySettings`, `FieldOverride`,
    `BackstopCredentialSecret`), so the tuning knobs a deployment sets are the ones every request
    actually uses.
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
    backstop_clients = create_backstop_client_factory(
        transport_settings(backstop_config), retry_settings(backstop_config)
    )
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
        overrides=_field_overrides(backstop_config.custom_field_overrides),
        ttl_minutes=backstop_config.custom_field_schema_ttl_minutes,
    )
    employment_index_factory = create_employment_index_factory(
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
        )
    )

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncGenerator[None, None]:
        async with (
            warmup_lifespan(
                custom_fields_service,
                backstop_clients,
                _service_account_credential(backstop_config),
            ),
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
            )
        ],
        lifespan=lifespan,
    )
    for fn in TOOLS:
        mcp.add_tool(fn)

    # Mounts /probe, /health, /metrics and returns HTTP request-metrics middleware.
    ops_middleware = setup_ops(mcp)

    @mcp.custom_route("/ready", methods=["GET"])
    async def ready(_request: Request) -> JSONResponse:
        """Postgres readiness — stock `setup_ops` `/probe` is process-up only."""
        return await _ready_response(
            engine, custom_fields_schema_loaded=custom_fields_service.has_definitions
        )

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
    to `BackstopConfig` that the transport should see is then a visible edit here, and one it
    should *not* see (the service account, the custom-field overrides) simply never appears.
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


def _service_account_credential(config: BackstopConfig) -> BackstopCredentialSecret | None:
    """The optional startup-warming credential, or None when none is configured.

    Assembled here so `custom_fields/warmup.py` is handed a credential rather than reaching
    through the client factory for a config object — `BackstopConfig` validates that the two
    halves are set together, so one `None` check covers both.
    """
    if config.service_username is None or config.service_api_token is None:
        return None
    return BackstopCredentialSecret(
        username=config.service_username, api_token=config.service_api_token
    )


def _field_overrides(
    configured: dict[str, CustomFieldOverrideConfig],
) -> dict[str, FieldOverride]:
    """Translate the env-parsed override shape into the custom-field feature's own type.

    The composition root is where a config shape becomes a domain one, which is what lets
    `features/custom_fields` stay free of any `config` import.
    """
    return {
        key: FieldOverride(
            display_name=override.display_name,
            aliases=tuple(override.aliases),
            description=override.description,
        )
        for key, override in configured.items()
    }


async def _ready_response(
    engine: AsyncEngine, *, custom_fields_schema_loaded: bool
) -> JSONResponse:
    """Readiness, reporting the checks it actually ran.

    Postgres is a hard dependency — OAuth token validation reads it on every request — so an
    unreachable database means not ready. The custom-field schema is reported but never gates
    readiness: it fills lazily by design, and tools degrade to `list_custom_fields` without it.
    """
    database_ok = True
    try:
        async with engine.connect() as connection:
            _ = await connection.execute(text("SELECT 1"))
    except Exception:
        database_ok = False
        logger.warning("ready.database_unreachable", exc_info=True)

    checks = {"database": database_ok, "custom_field_schema": custom_fields_schema_loaded}
    return JSONResponse(
        {"status": "healthy" if database_ok else "unhealthy", "checks": checks},
        status_code=200 if database_ok else 503,
    )
