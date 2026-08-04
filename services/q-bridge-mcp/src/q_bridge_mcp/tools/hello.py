from __future__ import annotations

from fastmcp.dependencies import TokenClaim
from fastmcp.tools import tool


@tool
def hello_world(
    name: str = TokenClaim("name"),  # pyright: ignore[reportCallInDefaultInitializer]
) -> str:
    """Greet the authenticated Zitadel user by name."""
    return f"Hello, {name}!"
