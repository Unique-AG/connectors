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
from office_mcp.server import GRAPH_SCOPES, ready_response, register_tools


def create_app(
    config: AppConfig | None = None,
    database_config: DatabaseConfig | None = None,
    entra_config: EntraConfig | None = None,
) -> Starlette:
    """The composition root.

    Every config object and every long-lived collaborator is built exactly once here and then
    injected. Nothing downstream re-reads the environment: `graph_client` in particular is handed
    its own frozen `GraphSettings` rather than being allowed to read config, and the tools are
    handed the one HTTP transport built from it.
    """
    config = config or AppConfig()
    database_config = database_config or DatabaseConfig()
    # `EntraConfig`'s fields are required with no defaults, which pyright reads as missing
    # arguments; pydantic-settings fills them from the environment. Deliberately not given
    # placeholder defaults: a missing app registration must fail at startup, by name.
    entra_config = entra_config or EntraConfig()  # pyright: ignore[reportCallIssue]

    configure_logging(config)
    configure_metrics(config)

    # The OAuth state store is this service's only connection to Postgres. It is built here
    # rather than inside `build_auth` so that one object serves both consumers: the auth
    # provider that depends on it, and the readiness probe that has to prove it works.
    oauth_storage = build_oauth_storage(entra_config, database_config)
    auth = build_auth(
        entra_config,
        base_url=config.issuer,
        client_storage=oauth_storage,
        graph_scopes=GRAPH_SCOPES,
    )
    # `GraphSettings`' defaults are what this service wants (see its docstring: interactive-call
    # timeouts, the SDK's own retry count). It is still built here rather than inside
    # `graph_client`, because the composition root is where a knob would have to be mapped from
    # `AppConfig` the day an operator needs a different value.
    graph_transport = create_graph_transport(GraphSettings())

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncGenerator[None, None]:
        try:
            yield
        finally:
            # The Graph transport is a connection pool shared by every tool call, and one
            # On-Behalf-Of credential is cached per signed-in user, each holding an open HTTP
            # transport of its own. The OAuth state store is deliberately not closed here: its
            # asyncpg pool dies with the process, and the wrapper chain `oauth_storage` names
            # publishes get/put/delete only — no close — so shutting the pool down would mean
            # reaching through the encryption wrapper for a store the process is about to drop
            # anyway.
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

    # Mounts /probe, /health, /metrics and returns HTTP request-metrics middleware.
    ops_middleware = setup_ops(mcp)

    @mcp.custom_route("/ready", methods=["GET"])
    async def ready(_request: Request) -> JSONResponse:
        """Postgres readiness — stock `setup_ops` `/probe` is process-up only.

        Asks the OAuth state store, which is the connection every sign-in goes through. See
        `server/readiness.py` for why it must not be a connection of its own.
        """
        return await ready_response(oauth_storage)

    return mcp.http_app(
        middleware=[
            Middleware(OpenTelemetryMiddleware),
            ops_middleware,
        ]
    )
