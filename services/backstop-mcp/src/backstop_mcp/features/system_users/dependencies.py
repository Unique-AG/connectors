from functools import lru_cache

from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.db import read_session
from backstop_mcp.dependencies import (
    get_backstop_client_for_current_caller,
    get_backstop_config,
    get_current_caller_subject,
    get_session_factory,
)
from backstop_mcp.features.auth import get_system_user_cache
from backstop_mcp.features.system_users.internal_dto import SystemUserDto
from backstop_mcp.features.system_users.system_users_service import SystemUsersService


@lru_cache(maxsize=1)
def get_system_users_service(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> SystemUsersService:
    # CACHING CANDIDATE, off unless `BACKSTOP_SYSTEM_USER_CACHE_ENABLED=true`: by default every
    # read walks `/system-users`. Decide from the two histograms in `caching/cached_value.py`
    # — `catalog_get_duration_seconds_count{catalog="system-user"}` is the demand a TTL would
    # absorb, `catalog_fetch_duration_seconds{catalog="system-user"}` what one walk costs.
    config = get_backstop_config()
    return SystemUsersService.with_ttl_minutes(
        client=client,
        ttl_minutes=config.system_user_ttl_minutes,
        caching_enabled=config.system_user_cache_enabled,
    )


async def get_current_caller_system_user(
    subject: str | None = Depends(get_current_caller_subject),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> SystemUserDto:
    """The system user cached on the credential row at login, for `author` on a write.

    Looked up by the access-token `subject` — that is our `backstop_credentials.user_id`.
    A missing snapshot means this connection predates the cache; reconnecting writes it.
    """
    if subject is None:
        raise ToolError(
            "Not connected to Backstop yet — add this MCP server to your client and "
            + "complete the login flow first."
        )
    async with read_session(session_factory) as session:
        cached = await get_system_user_cache(session, subject)
    if cached is None:
        raise ToolError(
            "No cached Backstop system user for this connection, so activities cannot "
            + "be authored. Reconnect this MCP server and complete the login flow."
        )
    _external_user_id, raw = cached
    return SystemUserDto.model_validate(raw)
