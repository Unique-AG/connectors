from __future__ import annotations

from q_bridge_mcp.config.settings import settings
from q_bridge_mcp.server import create_server


def main() -> None:
    create_server().run(
        transport="streamable-http",
        host=settings.host,
        port=settings.port,
    )


if __name__ == "__main__":
    main()
