from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from unique_mcp.monitoring import setup_ops

from office_mcp.auth import build_auth, build_oauth_storage
from office_mcp.config import AppConfig, DatabaseConfig, EntraConfig
from office_mcp.graph_client import GraphSettings, create_graph_transport
from office_mcp.logging import configure_logging
from office_mcp.metrics import configure_metrics
from office_mcp.server import ready_response
from office_mcp.tools import GRAPH_SCOPES, register_tools

# Intent: GRAPH_SCOPES is re-exported because tools derive it from their own GRAPH_PERMISSIONS.
# If a permission was not consented at authorization time, the later token exchange fails with
# AADSTS65001. All tools must declare their permissions; build_auth requests all of them at sign-in.
__all__ = ["GRAPH_SCOPES", "create_app"]


def create_app(
    config: AppConfig | None = None,
    database_config: DatabaseConfig | None = None,
    entra_config: EntraConfig | None = None,
) -> Starlette:
    """Compose the app. Every long-lived object is built once and injected."""
    config = config or AppConfig()
    database_config = database_config or DatabaseConfig()
    entra_config = entra_config or EntraConfig()  # pyright: ignore[reportCallIssue]

    configure_logging(config)
    configure_metrics(config)

    # Design decision: oauth_storage is built in the composition root because it serves both the
    # auth provider and the readiness probe.
    oauth_storage = build_oauth_storage(entra_config, database_config)
    auth = build_auth(
        entra_config,
        base_url=config.issuer,
        client_storage=oauth_storage,
        graph_scopes=GRAPH_SCOPES,
    )
    # Architectural rationale: GraphSettings() is built in the composition root, not inside
    # graph_client, because it is a stable value that must be held for the app lifetime.
    graph_transport = create_graph_transport(GraphSettings())

    # Architectural constraint: Nothing downstream re-reads the environment. Configuration is
    # captured at startup and injected. This makes behavior deterministic and testable.

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncGenerator[None, None]:
        try:
            yield
        finally:
            await graph_transport.aclose()
            await auth.close_obo_credentials()

    mcp = FastMCP(
        "Office MCP",
        version=config.version,
        auth=auth,
        middleware=[],
        lifespan=lifespan,
    )
    register_tools(mcp, graph_transport)

    ops_middleware = setup_ops(mcp)

    @mcp.custom_route("/ready", methods=["GET"])
    async def ready(_request: Request) -> JSONResponse:
        """Check Postgres readiness by asking the OAuth store."""
        return await ready_response(oauth_storage)

    return mcp.http_app(
        middleware=[
            Middleware(OpenTelemetryMiddleware),
            ops_middleware,
        ]
    )
