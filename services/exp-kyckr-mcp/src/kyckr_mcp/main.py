from importlib.metadata import version
from typing import Any, override

from fastmcp import FastMCP
from fastmcp.server.http import HostOriginGuardMiddleware
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send
from unique_mcp.logging import configure_logging
from unique_mcp.monitoring import setup_ops
from unique_toolkit.monitoring import configure_tracing

from kyckr_mcp.server import create_server
from kyckr_mcp.settings import Settings

OPS_PATHS = frozenset({"/probe", "/health", "/metrics"})
_MCP_PATH_LABEL = "/:mcpApiKey"
_REAL_PATH = "kyckr_real_path"


class _OpsExemptGuard(HostOriginGuardMiddleware):
    @override
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] in OPS_PATHS:
            await self.app(scope, receive, send)
        else:
            await super().__call__(scope, receive, send)


class _HideMcpApiKey:
    """Swap the secret path prefix for a template so the metrics middleware never sees it."""

    def __init__(self, app: ASGIApp, prefix: str) -> None:
        self.app = app
        self.prefix = prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] == "http" and (path == self.prefix or path.startswith(f"{self.prefix}/")):
            scope = {**scope, "path": _MCP_PATH_LABEL + path[len(self.prefix) :], _REAL_PATH: path}
        await self.app(scope, receive, send)


class _RestoreMcpApiKey:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if _REAL_PATH in scope:
            scope = {**scope, "path": scope[_REAL_PATH]}
        await self.app(scope, receive, send)


def _metrics_without_api_key(settings: Settings, metrics: Middleware) -> list[Middleware]:
    prefix = f"/{settings.mcp_api_key.get_secret_value()}"
    return [Middleware(_HideMcpApiKey, prefix=prefix), metrics, Middleware(_RestoreMcpApiKey)]


def _host_origin_guard(settings: Settings, origins: list[str]) -> Middleware:
    return Middleware(
        _OpsExemptGuard,
        allowed_hosts=settings.allowed_hosts,
        allowed_origins=[settings.base_url, *origins],
        mode="strict",
    )


def build_middleware(settings: Settings, ops_middleware: Middleware) -> list[Middleware]:
    origins = [str(url).rstrip("/") for url in settings.mcp_allowed_origins]
    return [
        _host_origin_guard(settings, origins),
        Middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "Mcp-Protocol-Version",
                "Mcp-Session-Id",
            ],
            expose_headers=["Mcp-Session-Id"],
        ),
        *_metrics_without_api_key(settings, ops_middleware),
    ]


def http_options(mcp: FastMCP, settings: Settings) -> dict[str, Any]:
    """What `mcp.run` and `mcp.http_app` both take, so tests serve the app that production does."""
    return {
        "path": settings.mcp_path,
        "stateless_http": True,
        "host_origin_protection": False,
        "middleware": build_middleware(settings, setup_ops(mcp)),
    }


def _run_server(mcp: FastMCP, settings: Settings) -> None:
    mcp.run(
        transport="streamable-http",
        host=settings.host,
        port=settings.port,
        uvicorn_config={"access_log": False},
        **http_options(mcp, settings),
    )


def main() -> None:
    settings = Settings()  # pyright: ignore[reportCallIssue]
    configure_tracing(service_name="exp-kyckr-mcp", service_version=version("kyckr-mcp"))
    configure_logging(level=settings.log_level)
    _run_server(create_server(settings), settings)


if __name__ == "__main__":
    main()
