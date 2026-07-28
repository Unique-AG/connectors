from __future__ import annotations

import os

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

PORT = int(os.environ.get("PORT", "8000"))

mcp = FastMCP("Hello MCP")


@mcp.tool
def hello(name: str) -> str:
    return f"Hello, {name}!"


@mcp.custom_route("/probe", methods=["GET"])
async def probe(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def main() -> None:
    mcp.run(transport="http", host="0.0.0.0", port=PORT, path="/mcp")


if __name__ == "__main__":
    main()
