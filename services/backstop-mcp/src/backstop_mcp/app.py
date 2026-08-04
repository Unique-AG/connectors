from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backstop_mcp.auth import context as auth_context
from backstop_mcp.auth.crypto import load_key
from backstop_mcp.auth.provider import BackstopOAuthProvider
from backstop_mcp.config import AppConfig, BackstopConfig, DatabaseConfig, EncryptionConfig
from backstop_mcp.custom_fields import (
    configure_custom_fields_service,
    create_custom_fields_service,
)
from backstop_mcp.custom_fields.middleware import CustomFieldGlossaryMiddleware
from backstop_mcp.custom_fields.warmup import warmup_lifespan
from backstop_mcp.db.engine import create_engine, create_session_factory
from backstop_mcp.logging import configure_logging
from backstop_mcp.metrics import configure_metrics, metrics_endpoint
from backstop_mcp.middleware import TraceContextMiddleware
from backstop_mcp.tools.get_organization import get_organization
from backstop_mcp.tools.get_organization_custom_field import get_organization_custom_field
from backstop_mcp.tools.resolve_custom_field import resolve_custom_field
from backstop_mcp.tools.system_info import get_system_info


def create_app(
    config: AppConfig | None = None,
    backstop_config: BackstopConfig | None = None,
    database_config: DatabaseConfig | None = None,
    encryption_config: EncryptionConfig | None = None,
) -> Starlette:
    config = config or AppConfig()
    backstop_config = backstop_config or BackstopConfig()
    database_config = database_config or DatabaseConfig()
    encryption_config = encryption_config or EncryptionConfig()

    configure_logging(config)
    configure_metrics(config)

    engine = create_engine(database_config)
    session_factory = create_session_factory(engine)
    encryption_key = load_key(encryption_config)

    auth_provider = BackstopOAuthProvider(
        base_url=config.public_base_url,
        session_factory=session_factory,
        encryption_key=encryption_key,
        backstop_base_url=backstop_config.base_url,
    )
    auth_context.configure(
        auth_context.BackstopAuthContext(
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
    configure_custom_fields_service(custom_fields_service)

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncGenerator[None, None]:
        async with warmup_lifespan(custom_fields_service, backstop_config):
            yield

    mcp = FastMCP(
        "Backstop MCP",
        version=config.version,
        auth=auth_provider,
        middleware=[CustomFieldGlossaryMiddleware()],
        lifespan=lifespan,
    )
    mcp.tool(get_system_info)
    mcp.tool(get_organization)
    mcp.tool(resolve_custom_field)
    mcp.tool(get_organization_custom_field)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @mcp.custom_route("/probe", methods=["GET"])
    async def probe(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "healthy", "checks": {}})

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
