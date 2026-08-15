from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from opentelemetry.metrics import NoOpMeterProvider
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from unique_mcp.monitoring import setup_ops
from unique_toolkit.monitoring import configure_tracing

from office_mcp.auth import build_auth, build_oauth_storage
from office_mcp.config import AppConfig, DatabaseConfig, EntraConfig
from office_mcp.graph_client import GraphSettings, create_graph_transport
from office_mcp.logging import configure_logging
from office_mcp.metrics import configure_metrics
from office_mcp.server import ready_response
from office_mcp.tools import GRAPH_SCOPES, register_tools

# Every Graph permission any tool might redeem, which the auth provider has to have at startup: one
# never consented to cannot be obtained later, and the On-Behalf-Of exchange fails with AADSTS65001
# before the tool body runs. One source, re-exported rather than re-derived — `tools/__init__.py`
# assembles it from the tool modules themselves, in a stable order, and this name is here so that
# `create_app` and its test have one thing to read.
__all__ = ["GRAPH_SCOPES", "create_app"]


def create_app(
    config: AppConfig | None = None,
    database_config: DatabaseConfig | None = None,
    entra_config: EntraConfig | None = None,
) -> Starlette:
    """Composition root.

    Every config object and long-lived collaborator is built exactly once and injected. Nothing
    downstream re-reads the environment: `graph_client` in particular is handed its own frozen
    `GraphSettings` rather than being allowed to read config, and the tools are handed the one
    HTTP transport built from it.
    """
    config = config or AppConfig()
    database_config = database_config or DatabaseConfig()
    # EntraConfig fields are required; pydantic-settings fills them from the environment.
    # No placeholder defaults: a missing app registration fails at startup by name.
    entra_config = entra_config or EntraConfig()  # pyright: ignore[reportCallIssue]

    configure_logging(config)
    configure_metrics(config)
    # Here, beside configure_metrics, rather than in main.py where kb-mcp puts it: everything that
    # depends on a tracer provider — OpenTelemetryMiddleware, the two middlewares below, FastMCP's
    # own spans — is assembled in this function, and main.py is not the only caller of it. Installed
    # from main.py, `create_app()` would compose an instrumented app against a provider only the CLI
    # entrypoint had installed. kb-mcp's main() *is* its composition root, so its placement is the
    # same decision, not a different one.
    # The version is passed rather than left to TracingSettings, which would read the bare VERSION
    # env var: config.version is this service's one source of truth for it, as in metrics.py.
    # Self-disabling when no OTEL_* variable is set, so a test process stays untraced.
    configure_tracing(service_name="office-mcp", service_version=config.version)

    # OAuth store is the only Postgres connection. Built here (not in build_auth) so one
    # object serves both the auth provider and the readiness probe.
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
            # Close the shared Graph transport pool, then the per-user OBO credentials and their
            # open HTTP transports. Don't close the OAuth store: reaching through the encryption
            # wrapper for a store the process is about to drop anyway is not worth the
            # complexity. Its asyncpg pool dies with the process.
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
        """Postgres readiness. `setup_ops` `/probe` is process-up only.

        Ask the OAuth store (the connection every sign-in uses). See `server/readiness.py`
        for why not a separate connection.
        """
        return await ready_response(oauth_storage)

    return mcp.http_app(
        middleware=[
            # A no-op meter provider on purpose. Left to the global one, this middleware's own
            # instruments resolve against the provider metrics.py aims at the toolkit registry, and
            # /metrics then serves two histograms for one latency: http_server_duration_milliseconds
            # beside unique_toolkit's python_http_request_duration_seconds. The toolkit series is
            # the one the house dashboards read, and its python_http_requests_in_progress covers
            # what http_server_active_requests would have said, so the toolkit series stays the only
            # one. Spans are unaffected — the tracer provider is untouched.
            Middleware(OpenTelemetryMiddleware, meter_provider=NoOpMeterProvider()),
            ops_middleware,
        ]
    )
