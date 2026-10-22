"""Serve the knowledge base icon at /favicon.ico: the MCP hub reads a server's icon from there."""

from pathlib import Path

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import Response

_FAVICON = (Path(__file__).parent / "assets" / "favicon.svg").read_bytes()


def add_favicon_route(mcp: FastMCP) -> None:
    @mcp.custom_route("/favicon.ico", methods=["GET"])
    async def favicon(_request: Request) -> Response:
        return Response(
            _FAVICON,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400"},
        )
