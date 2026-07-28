from fastmcp import FastMCP
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backstop_mcp.config import AppConfig
from backstop_mcp.logging import configure_logging
from backstop_mcp.metrics import configure_metrics, metrics_endpoint
from backstop_mcp.middleware import TraceContextMiddleware


def create_app(config: AppConfig | None = None) -> Starlette:
    config = config or AppConfig()

    configure_logging(config)
    configure_metrics(config)

    mcp = FastMCP("Backstop MCP", version=config.version)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @mcp.custom_route("/probe", methods=["GET"])
    async def probe(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "healthy", "checks": {}})

    @mcp.custom_route("/metrics", methods=["GET"])
    async def metrics_route(request: Request) -> Response:
        return await metrics_endpoint(request)

    return mcp.http_app(
        middleware=[
            Middleware(OpenTelemetryMiddleware),
            Middleware(TraceContextMiddleware),
        ]
    )
