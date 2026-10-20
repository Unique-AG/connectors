from collections.abc import Sequence
from typing import override

from fastmcp.server.http import HostOriginGuardMiddleware
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.types import Receive, Scope, Send

from mcp_runtime.settings import ServerSettings

OPS_PATHS = frozenset({"/probe", "/health", "/metrics"})


def build_middleware(settings: ServerSettings, own: Sequence[Middleware]) -> list[Middleware]:
    """The host and origin guard, then CORS, then the MCP's own middleware in its order."""
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
        *own,
    ]


class _OpsExemptGuard(HostOriginGuardMiddleware):
    """Kubernetes probes and Prometheus reach the pod by IP, so the ops routes skip the guard."""

    @override
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] in OPS_PATHS:
            await self.app(scope, receive, send)
        else:
            await super().__call__(scope, receive, send)
