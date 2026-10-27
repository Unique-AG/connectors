# mcp-scaffold-commit: 9a91a8864afe, timestamp: 2026-10-21T12:09:32+00:00

from typing import Literal, TypedDict

from fastmcp import FastMCP
from fastmcp.server.http import StarletteWithLifespan
from mcp_configs import ServerSettings
from starlette.middleware import Middleware

from architecture_demo_mcp.mcp.middleware import http_middleware


def run_server(mcp: FastMCP, settings: ServerSettings) -> None:
    """Serves `mcp` over streamable HTTP at `/mcp`, behind `http_middleware`.

    A server without an auth provider only binds to loopback: every tool would otherwise answer
    anyone who reaches the pod, with the MCP's own upstream credentials and storage.
    """
    if mcp.auth is None and not settings.binds_to_loopback:
        raise RuntimeError(
            f"{mcp.name} has no auth provider, so it only serves on loopback, not on "
            f"HOST={settings.host}. Pass one to FastMCP(auth=...) to serve beyond this machine."
        )
    mcp.run(
        transport="streamable-http",
        host=settings.host,
        port=settings.port,
        uvicorn_config={"access_log": False},
        **_http_options(mcp, settings),
    )


def http_app(mcp: FastMCP, settings: ServerSettings) -> StarletteWithLifespan:
    """The app `run_server` serves, for tests."""
    return mcp.http_app(transport="streamable-http", **_http_options(mcp, settings))


class _HttpOptions(TypedDict):
    path: str
    stateless_http: bool
    host_origin_protection: Literal[False]
    middleware: list[Middleware]


def _http_options(mcp: FastMCP, settings: ServerSettings) -> _HttpOptions:
    return {
        "path": "/mcp",
        "stateless_http": True,
        # The guard in http_middleware replaces it, so the ops routes can skip it.
        "host_origin_protection": False,
        "middleware": http_middleware(mcp, settings),
    }
