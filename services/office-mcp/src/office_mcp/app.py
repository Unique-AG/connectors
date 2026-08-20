import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from opentelemetry.metrics import NoOpMeterProvider
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from unique_mcp.monitoring import setup_ops
from unique_toolkit.monitoring import configure_tracing

from office_mcp.auth import build_auth, build_oauth_storage
from office_mcp.config import AppConfig, DatabaseConfig, EntraConfig, SurfaceConfig
from office_mcp.graph_client import GraphSettings, create_graph_transport
from office_mcp.logging import HttpRequestIdMiddleware, configure_logging
from office_mcp.metrics import configure_metrics
from office_mcp.server import ready_response, surface_manifest
from office_mcp.shared.seam import GraphAdviceMiddleware
from office_mcp.tools import graph_advice, register_tools, resolve
from office_mcp.tracing import TraceContextCaptureMiddleware, TraceContextRestoreMiddleware

__all__ = ["create_app"]

logger = logging.getLogger(__name__)

# `prometheus_client`'s own default layout, plus four boundaries above it. One inbound MCP request
# contains a tool call and every Graph call that tool made, and the Graph timeout budget says how
# long that is: 30 s per request (`GraphSettings.request_timeout_seconds`) times four attempts
# (`max_retries=3`) is 120 s before any Retry-After wait, and a paged walk is several requests. Left
# to the default, whose top finite bucket is 10 s, every one of those lands in `+Inf` and p95 and
# p99 both read 10 — the slow tail this histogram exists to show becomes the one thing it cannot
# say. This is also the only one of the three latency histograms whose buckets this service gets to
# choose: the Graph one is a view in `metrics.py`, and `unique_mcp`'s tool-call one is fixed
# upstream.
#
# Trap: the histogram is registered once per process and the first middleware to declare it wins its
# buckets, so this has to travel on the `setup_ops` call and cannot be corrected later.
_HTTP_DURATION_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.075,
    0.1,
    0.25,
    0.5,
    0.75,
    1.0,
    2.5,
    5.0,
    7.5,
    10.0,
    30.0,
    60.0,
    120.0,
    300.0,
)


def create_app(
    config: AppConfig | None = None,
    database_config: DatabaseConfig | None = None,
    entra_config: EntraConfig | None = None,
    surface_config: SurfaceConfig | None = None,
) -> Starlette:
    """Compose the app. Every long-lived object is built once and injected."""
    config = config or AppConfig()
    database_config = database_config or DatabaseConfig()
    entra_config = entra_config or EntraConfig()  # pyright: ignore[reportCallIssue]
    surface_config = surface_config or SurfaceConfig()

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

    # Design decision: the tool surface is resolved once, here, and both halves of it come from that
    # one resolution — the scopes sign-in asks for, and the modules that get registered. Resolving
    # twice would be two chances to disagree about a tool, and the disagreement is unfixable after
    # the fact: a permission not requested at sign-in cannot be redeemed by a later call.
    selection = resolve(preset=surface_config.tools_preset, enabled=surface_config.tools_enabled)

    # Design decision: oauth_storage is built in the composition root because it serves both the
    # auth provider and the readiness probe.
    oauth_storage = build_oauth_storage(entra_config, database_config)
    auth = build_auth(
        entra_config,
        base_url=config.issuer,
        client_storage=oauth_storage,
        graph_scopes=selection.graph_scopes,
    )
    # Architectural rationale: GraphSettings() is built in the composition root, not inside
    # graph_client. The composition root is the place to map a knob from AppConfig. An
    # operator may need a different value some day.
    graph_transport = create_graph_transport(GraphSettings())

    # Architectural constraint: Nothing downstream re-reads the environment. Configuration is
    # captured at startup and injected. This makes behavior deterministic and testable.

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncGenerator[None, None]:
        # In the lifespan rather than above, because the manifest reads the registered tools' own
        # prose to say which of it points at a tool this deployment does not expose, and that is
        # only readable once they are registered — and only awaitable here.
        logger.info(await surface_manifest(server, selection, version=config.version))
        try:
            yield
        finally:
            await graph_transport.aclose()
            await auth.close_obo_credentials()
            # This does not close oauth_storage. Reaching through its encryption wrapper is
            # not worth it when the process ends anyway. Its connection pool ends with the
            # process.

    mcp = FastMCP(
        "Office MCP",
        version=config.version,
        auth=auth,
        # A middleware passed here ends up outermost, ahead of FastMCP's own and of the
        # operations layer `setup_ops` appends below, and that is where the advice one belongs: a
        # client reads the polished refusal while the operations layer still logs the untranslated
        # failure and the cause chain under it. The table comes from the same resolution that
        # registers the tools, so it cannot name a tool this deployment does not expose.
        middleware=[
            GraphAdviceMiddleware(graph_advice(selection)),
            TraceContextRestoreMiddleware(),
        ],
        lifespan=lifespan,
    )
    register_tools(mcp, graph_transport, selection)

    ops_middleware = setup_ops(mcp, duration_buckets=_HTTP_DURATION_BUCKETS)

    @mcp.custom_route("/ready", methods=["GET"])
    async def ready(_request: Request) -> JSONResponse:
        """Check Postgres readiness by asking the OAuth store."""
        return await ready_response(oauth_storage)

    @mcp.custom_route("/manifest", methods=["GET"])
    async def manifest(_request: Request) -> PlainTextResponse:
        """The resolved tool surface, so it can be read without going through the pod's logs.

        Unauthenticated on purpose, and it leaks nothing: the same scope list is already visible in
        the authorize URL every user's browser is sent to.
        """
        return PlainTextResponse(await surface_manifest(mcp, selection, version=config.version))

    # Order here is outside-in and load-bearing: OpenTelemetryMiddleware has to have made the
    # request's server span current before TraceContextCaptureMiddleware records the context, or
    # every MCP span is parented to the request's parent instead of the request. See tracing.py.
    return mcp.http_app(
        middleware=[
            # Outermost, so a request that never reaches the app is still one identifiable request
            # in the logs. See `logging.py`.
            Middleware(HttpRequestIdMiddleware),
            # A no-op meter provider on purpose. Left to the global one, this middleware's own
            # instruments resolve against the provider metrics.py aims at the toolkit registry, and
            # /metrics then serves two histograms for one latency: http_server_duration_milliseconds
            # beside unique_toolkit's python_http_request_duration_seconds. The toolkit series is
            # the one the house dashboards read, and its python_http_requests_in_progress covers
            # what http_server_active_requests would have said, so the toolkit series stays the only
            # one. Spans are unaffected — the tracer provider is untouched.
            Middleware(OpenTelemetryMiddleware, meter_provider=NoOpMeterProvider()),
            Middleware(TraceContextCaptureMiddleware),
            ops_middleware,
        ]
    )
