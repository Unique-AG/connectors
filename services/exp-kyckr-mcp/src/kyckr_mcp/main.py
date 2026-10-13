import asyncio
from importlib.metadata import version
from typing import override

from fastmcp import FastMCP
from fastmcp.server.http import HostOriginGuardMiddleware
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.types import Receive, Scope, Send
from unique_mcp.logging import configure_logging
from unique_mcp.monitoring import setup_ops
from unique_toolkit.monitoring import configure_tracing

from kyckr_mcp.server import create_server
from kyckr_mcp.settings import Settings
from kyckr_mcp.tools import register_tools

OPS_PATHS = frozenset({"/probe", "/health", "/metrics"})


class OpsExemptGuard(HostOriginGuardMiddleware):
    @override
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] in OPS_PATHS:
            await self.app(scope, receive, send)
        else:
            await super().__call__(scope, receive, send)


def host_origin_guard(settings: Settings, origins: list[str]) -> Middleware:
    return Middleware(
        OpsExemptGuard,
        allowed_hosts=settings.allowed_hosts,
        allowed_origins=[settings.base_url, *origins],
        mode="strict",
    )


def run_server(mcp: FastMCP, settings: Settings) -> None:
    origins = [str(url).rstrip("/") for url in settings.mcp_allowed_origins]
    ops_middleware = setup_ops(mcp)
    mcp.run(
        transport="streamable-http",
        host=settings.host,
        port=settings.port,
        path=settings.mcp_path,
        stateless_http=True,
        host_origin_protection=False,
        middleware=[
            host_origin_guard(settings, origins),
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
            ops_middleware,
        ],
        uvicorn_config={"access_log": False},
    )


def main() -> None:
    settings = Settings()  # pyright: ignore[reportCallIssue]
    configure_tracing(service_name="exp-kyckr-mcp", service_version=version("kyckr-mcp"))
    configure_logging(level=settings.log_level)
    mcp = create_server(settings)
    asyncio.run(register_tools(mcp, settings))
    run_server(mcp, settings)


if __name__ == "__main__":
    main()
