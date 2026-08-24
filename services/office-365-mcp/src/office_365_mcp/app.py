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

from office_365_mcp.auth import build_auth, build_oauth_storage
from office_365_mcp.cardinality import BoundedNameMiddleware, BoundedRequestMiddleware
from office_365_mcp.config import AppConfig, DatabaseConfig, EntraConfig, SurfaceConfig
from office_365_mcp.graph_client import GraphSettings, create_graph_transport
from office_365_mcp.logging import (
    HttpRequestIdMiddleware,
    MessageLogMiddleware,
    configure_logging,
)
from office_365_mcp.metrics import configure_metrics
from office_365_mcp.server import ready_response, surface_manifest
from office_365_mcp.shared.seam import GraphAdviceMiddleware
from office_365_mcp.tools import graph_advice, register_tools, resolve
from office_365_mcp.tracing import TraceContextCaptureMiddleware, TraceContextRestoreMiddleware

__all__ = ["create_app"]

logger = logging.getLogger(__name__)

# `prometheus_client`'s default layout plus four boundaries above it. One inbound MCP request holds
# a tool call and every Graph call that tool made: 30 s per request times four attempts is 120 s
# before any Retry-After wait, and a paged walk is several requests. The default's top finite bucket
# is 10 s, so every one of those lands in `+Inf` and p95 and p99 both read 10.
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
    # Here rather than in `main.py`: everything below depends on a tracer provider, and tests call
    # `create_app()` too. The version is passed rather than left to `TracingSettings`, which would
    # read the bare `VERSION` env var. `configure_tracing` disables itself when no `OTEL_*` variable
    # is set, so tests stay untraced.
    configure_tracing(service_name="office-365-mcp", service_version=config.version)

    # Resolved once: the scopes sign-in asks for and the modules that get registered come from the
    # same resolution, and a permission not requested at sign-in cannot be redeemed by a later call.
    selection = resolve(preset=surface_config.tools_preset, enabled=surface_config.tools_enabled)

    oauth_storage = build_oauth_storage(entra_config, database_config)
    auth = build_auth(
        entra_config,
        base_url=config.issuer,
        client_storage=oauth_storage,
        graph_scopes=selection.graph_scopes,
    )
    # Built here, not inside `graph_client/`, which may be told its timeout budget but never
    # configured (rule 2 in `tests/test_layering.py`).
    graph_transport = create_graph_transport(
        GraphSettings(
            request_timeout_seconds=config.graph_request_timeout_seconds,
            connect_timeout_seconds=config.graph_connect_timeout_seconds,
            max_retries=config.graph_max_retries,
        )
    )

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncGenerator[None, None]:
        # In the lifespan, not above: the manifest reads the registered tools' own prose, readable
        # only once they are registered and awaitable only here.
        logger.info(await surface_manifest(server, selection, version=config.version))
        try:
            yield
        finally:
            await auth.close_obo_credentials()
            # Neither `graph_transport` nor `oauth_storage` is closed. `graph_transport.aclose()`
            # is a no-op: the SDK's `AsyncGraphTransport` defines no `aclose` and inherits httpx's,
            # whose body is `pass` (microsoft/kiota-python#494, open). Both pools end with the
            # process.

    mcp = FastMCP(
        "Office 365 MCP",
        version=config.version,
        auth=auth,
        # Earlier in this list is further out: `add_middleware` appends and the chain is built over
        # `reversed(middleware)`. The first two are ordered for that, not for tidiness.
        #
        # The name one first, because `setup_ops`' metrics middleware labels a Prometheus counter
        # with the name the *client* sent, before anything has resolved it. See `cardinality.py`.
        # Then the advice one, outside the operations layer, so a client reads the polished refusal
        # while that layer still logs the untranslated failure.
        middleware=[
            BoundedNameMiddleware(),
            GraphAdviceMiddleware(graph_advice(selection)),
            TraceContextRestoreMiddleware(),
            # Inside the restore middleware, or its line carries the session task's stale trace.
            MessageLogMiddleware(),
        ],
        lifespan=lifespan,
    )
    register_tools(mcp, graph_transport, selection)

    ops_middleware = setup_ops(mcp, duration_buckets=_HTTP_DURATION_BUCKETS)

    @mcp.custom_route("/ready", methods=["GET"])
    async def ready(_request: Request) -> JSONResponse:
        return await ready_response(oauth_storage)

    @mcp.custom_route("/manifest", methods=["GET"])
    async def manifest(_request: Request) -> PlainTextResponse:
        """Unauthenticated on purpose, and it leaks nothing: the same scope list is already in the
        authorize URL every user's browser is sent to."""
        return PlainTextResponse(await surface_manifest(mcp, selection, version=config.version))

    # Outside-in and load-bearing: `OpenTelemetryMiddleware` must have made the request's server
    # span current before `TraceContextCaptureMiddleware` records the context, or every MCP span is
    # parented to the request's parent instead of the request. See `tracing.py`.
    return mcp.http_app(
        middleware=[
            # Outermost, so a request that never reaches the app is still identifiable in the
            # logs. See `logging.py`.
            Middleware(HttpRequestIdMiddleware),
            # Second, so the log line above keeps the path the client really asked for while nothing
            # below can turn one into a metric label or a span attribute. See `cardinality.py`.
            Middleware(BoundedRequestMiddleware),
            # A no-op meter provider on purpose: left to the global one that `metrics.py` aims at
            # the toolkit registry, `/metrics` serves two histograms for one latency,
            # `http_server_duration_milliseconds` beside unique_toolkit's
            # `python_http_request_duration_seconds`. Spans are unaffected.
            Middleware(OpenTelemetryMiddleware, meter_provider=NoOpMeterProvider()),
            Middleware(TraceContextCaptureMiddleware),
            ops_middleware,
        ]
    )
