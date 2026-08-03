from __future__ import annotations

from fastmcp import FastMCP

mcp = FastMCP("q-bridge-mcp")


@mcp.tool
def hello_world() -> str:
    """Return a hello-world greeting."""
    return "Hello, world!"


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
