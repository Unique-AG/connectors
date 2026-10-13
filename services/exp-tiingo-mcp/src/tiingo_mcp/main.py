import asyncio
from typing import override

from fastmcp.server.http import HostOriginGuardMiddleware
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.types import Receive, Scope, Send
from unique_mcp.logging import configure_logging
from unique_mcp.monitoring import setup_ops

from tiingo_mcp.server import create_server
from tiingo_mcp.settings import Settings
from tiingo_mcp.tools import register_tools

OPS_PATHS = frozenset({"/probe", "/health", "/metrics"})


class OpsExemptGuard(HostOriginGuardMiddleware):
    """FastMCP's Host/Origin guard, except for the ops routes that probes call by container IP."""

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


def main() -> None:
    # BaseSettings loads these required credentials from the environment at runtime.
    settings = Settings()  # pyright: ignore[reportCallIssue]
    configure_logging(level=settings.log_level)
    origins = [str(url).rstrip("/") for url in settings.mcp_allowed_origins]
    mcp = create_server(settings)
    asyncio.run(register_tools(mcp))
    # Mounts /probe, /health, /metrics and returns HTTP request-metrics middleware.
    ops_middleware = setup_ops(mcp)
    mcp.run(
        transport="streamable-http",
        host=settings.host,
        port=settings.port,
        path="/mcp",
        # Tools keep no per-session state and use no server-to-client requests.
        stateless_http=True,
        # FastMCP's own guard would also cover the ops routes, so OpsExemptGuard replaces it.
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
                expose_headers=["WWW-Authenticate", "Mcp-Session-Id"],
            ),
            ops_middleware,
        ],
        uvicorn_config={"access_log": False},
    )


if __name__ == "__main__":
    main()
