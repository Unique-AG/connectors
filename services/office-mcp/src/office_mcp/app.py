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
from office_mcp.logging import configure_logging
from office_mcp.metrics import configure_metrics
from office_mcp.server import ready_response


def create_app(
    config: AppConfig | None = None,
    database_config: DatabaseConfig | None = None,
    entra_config: EntraConfig | None = None,
) -> Starlette:
    """The composition root.

    Every config object and every long-lived collaborator is built exactly once here and then
    injected. Nothing downstream re-reads the environment. The Microsoft Graph client and the
    tools that use it land in later PRs, wired in here the same way — so the MCP endpoint below
    authenticates callers but exposes no tools yet.
    """
    config = config or AppConfig()
    database_config = database_config or DatabaseConfig()
    # `EntraConfig`'s fields are required with no defaults, which pyright reads as missing
    # arguments; pydantic-settings fills them from the environment. Deliberately not given
    # placeholder defaults: a missing app registration must fail at startup, by name.
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

    # The OAuth state store is this service's only connection to Postgres. It is built here
    # rather than inside `build_auth` so that one object serves both consumers: the auth
    # provider that depends on it, and the readiness probe that has to prove it works.
    oauth_storage = build_oauth_storage(entra_config, database_config)
    auth = build_auth(entra_config, base_url=config.issuer, client_storage=oauth_storage)

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncGenerator[None, None]:
        try:
            yield
        finally:
            # One On-Behalf-Of credential is cached per signed-in user, each holding an open
            # HTTP transport of its own. The OAuth state store is deliberately not closed here:
            # its asyncpg pool dies with the process, and the wrapper chain `oauth_storage`
            # names publishes get/put/delete only — no close — so shutting the pool down would
            # mean reaching through the encryption wrapper for a store the process is about to
            # drop anyway.
            await auth.close_obo_credentials()

    mcp = FastMCP(
        "Office MCP",
        version=config.version,
        auth=auth,
        middleware=[],
        lifespan=lifespan,
    )

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
