from contextlib import AbstractAsyncContextManager

from mcp_credential_auth import (
    cleanup_lifespan as shared_cleanup_lifespan,
)
from mcp_credential_auth import (
    purge_expired_auth_rows,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backstop_mcp.config import AuthConfig


def cleanup_lifespan(
    session_factory: async_sessionmaker[AsyncSession], config: AuthConfig
) -> AbstractAsyncContextManager[None]:
    return shared_cleanup_lifespan(
        session_factory,
        token_retention=config.token_retention,
        login_attempt_window=config.login_attempt_window,
        unused_client_retention=config.unused_client_retention,
        cleanup_interval=config.cleanup_interval,
    )


__all__ = ["cleanup_lifespan", "purge_expired_auth_rows"]
