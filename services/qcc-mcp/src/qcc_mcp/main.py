"""Entry point. `qcc-mcp` (or `python -m qcc_mcp.main`) starts the server.

Defaults to stdio transport (what an MCP client spawns). Set QCC_MCP_HTTP=1 to
serve over streamable HTTP on QCC_MCP_HOST:QCC_MCP_PORT instead.
"""

from __future__ import annotations

import os

from qcc_mcp.app import create_app


def main() -> None:
    mcp = create_app()
    if os.environ.get("QCC_MCP_HTTP") == "1":
        mcp.run(
            transport="http",
            host=os.environ.get("QCC_MCP_HOST", "127.0.0.1"),
            port=int(os.environ.get("QCC_MCP_PORT", "8000")),
        )
    else:
        mcp.run()  # stdio


if __name__ == "__main__":
    main()
