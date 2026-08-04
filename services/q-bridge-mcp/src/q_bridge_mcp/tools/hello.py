from __future__ import annotations

from fastmcp.dependencies import Depends, TokenClaim
from fastmcp.tools import tool

from q_bridge_mcp.dependencies import get_company_id, get_user_id
from q_bridge_mcp.profiles.dependencies import (
    QBridgeConfiguration,
    require_configuration,
)


@tool
def hello_world(
    name: str = TokenClaim("name"),  # pyright: ignore[reportCallInDefaultInitializer]
    user_id: str = Depends(get_user_id),  # pyright: ignore[reportCallInDefaultInitializer]
    company_id: str = Depends(get_company_id),  # pyright: ignore[reportCallInDefaultInitializer]
    _configuration: QBridgeConfiguration = Depends(  # noqa: B008  # pyright: ignore[reportCallInDefaultInitializer]
        require_configuration
    ),
) -> str:
    """Greet the authenticated Zitadel user by name."""
    return f"Hello, {name}! (user-id: {user_id}, company-id: {company_id})"
