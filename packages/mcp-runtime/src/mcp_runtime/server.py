from collections.abc import Sequence
from typing import Literal, TypedDict

from fastmcp import FastMCP
from fastmcp.server.http import StarletteWithLifespan
from starlette.middleware import Middleware

from mcp_runtime.middleware import build_middleware
from mcp_runtime.settings import ServerSettings
from mcp_runtime.settings.hosts import LOCAL_HOSTS


def run_server(
    mcp: FastMCP, settings: ServerSettings, middleware: Sequence[Middleware] = ()
) -> None:
    """Serve `mcp` over streamable HTTP at `/mcp`, with `middleware` inside the guard and CORS.

    A server without an auth provider only binds to loopback: every tool would otherwise answer
    anyone who reaches the pod, with the MCP's own upstream credentials and storage.
    """
    if mcp.auth is None and settings.host not in LOCAL_HOSTS:
        raise RuntimeError(
            f"{mcp.name} has no auth provider, so it only serves on loopback, not on "
            + f"HOST={settings.host}. Pass one to FastMCP(auth=...) to serve beyond this machine."
        )
    mcp.run(
        transport="streamable-http",
        host=settings.host,
        port=settings.port,
        uvicorn_config={"access_log": False},
        **_http_options(settings, middleware),
    )


def http_app(
    mcp: FastMCP, settings: ServerSettings, middleware: Sequence[Middleware] = ()
) -> StarletteWithLifespan:
    """The app `run_server` serves, for tests."""
    return mcp.http_app(transport="streamable-http", **_http_options(settings, middleware))


class _HttpOptions(TypedDict):
    path: str
    stateless_http: bool
    host_origin_protection: Literal[False]
    middleware: list[Middleware]


def _http_options(settings: ServerSettings, middleware: Sequence[Middleware]) -> _HttpOptions:
    return {
        "path": "/mcp",
        "stateless_http": True,
        # The guard in build_middleware replaces it, so the ops routes can skip it.
        "host_origin_protection": False,
        "middleware": build_middleware(settings, middleware),
    }
