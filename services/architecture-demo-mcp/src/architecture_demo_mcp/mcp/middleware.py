# mcp-scaffold-version: 0.0.1, timestamp: 2026-10-21T12:09:32+00:00

from typing import override

from fastmcp import FastMCP
from fastmcp.server.http import HostOriginGuardMiddleware
from mcp_configs import ServerSettings
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

from architecture_demo_mcp.telemetry import instrument

OPS_PATHS = frozenset({"/probe", "/health", "/metrics"})


def http_middleware(mcp: FastMCP, settings: ServerSettings) -> list[Middleware]:
    """The host and origin guard, then CORS, then the MCP's own HTTP middleware.

    Add the MCP's own after `instrument(mcp)`, such as a request id. MCP-level middleware, which
    sees tool calls rather than HTTP requests, goes on the server: `mcp.add_middleware(...)`.
    """
    return [
        Middleware(
            _OpsExemptGuard,
            allowed_hosts=settings.allowed_hosts,
            allowed_origins=[settings.base_url, *settings.allowed_origins],
            mode="strict",
        ),
        Middleware(
            CORSMiddleware,
            allow_origins=settings.allowed_origins,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "Mcp-Protocol-Version",
                "Mcp-Session-Id",
            ],
            # A browser client reads the auth pointer of a 401 from WWW-Authenticate.
            expose_headers=["WWW-Authenticate", "Mcp-Session-Id"],
        ),
        instrument(mcp),
    ]


class _OpsExemptGuard(HostOriginGuardMiddleware):
    """Kubernetes probes and Prometheus reach the pod by IP, so the ops routes skip the guard."""

    @override
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] in OPS_PATHS:
            await self.app(scope, receive, send)
        else:
            await super().__call__(scope, receive, send)
