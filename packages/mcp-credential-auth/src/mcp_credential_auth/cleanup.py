import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.engine import CursorResult, Result
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mcp_credential_auth.database import transaction
from mcp_credential_auth.models import (
    AuthorizationCode,
    LoginAttempt,
    OAuthClient,
    OAuthToken,
    PendingAuthorization,
)

logger = logging.getLogger(__name__)


def _deleted(result: Result[tuple[object, ...]]) -> int:
    assert isinstance(result, CursorResult)
    return result.rowcount


async def _delete_expired_pending(session: AsyncSession, now: datetime) -> int:
    result = await session.execute(
        delete(PendingAuthorization).where(PendingAuthorization.expires_at < now)
    )
    return _deleted(result)


async def _delete_expired_codes(session: AsyncSession, now: datetime) -> int:
    result = await session.execute(
        delete(AuthorizationCode).where(AuthorizationCode.expires_at < now.timestamp())
    )
    return _deleted(result)


async def _delete_old_token_families(session: AsyncSession, cutoff: datetime) -> int:
    live_families = select(OAuthToken.family_id).where(
        or_(
            OAuthToken.access_token_expires_at >= cutoff,
            OAuthToken.refresh_token_expires_at >= cutoff,
        )
    )
    result = await session.execute(
        delete(OAuthToken).where(OAuthToken.family_id.not_in(live_families))
    )
    return _deleted(result)


async def _delete_old_login_attempts(session: AsyncSession, cutoff: datetime) -> int:
    result = await session.execute(delete(LoginAttempt).where(LoginAttempt.attempted_at < cutoff))
    return _deleted(result)


async def _delete_unreferenced_clients(session: AsyncSession, cutoff: datetime) -> int:
    result = await session.execute(
        delete(OAuthClient).where(
            OAuthClient.created_at < cutoff,
            OAuthClient.client_id.not_in(select(PendingAuthorization.client_id)),
            OAuthClient.client_id.not_in(select(AuthorizationCode.client_id)),
            OAuthClient.client_id.not_in(select(OAuthToken.client_id)),
        )
    )
    return _deleted(result)


async def purge_expired_auth_rows(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    token_retention: timedelta,
    login_attempt_window: timedelta,
    unused_client_retention: timedelta,
) -> None:
    now = datetime.now(UTC)
    async with transaction(session_factory) as session:
        pending = await _delete_expired_pending(session, now)
        codes = await _delete_expired_codes(session, now)
        tokens = await _delete_old_token_families(session, now - token_retention)
        attempts = await _delete_old_login_attempts(session, now - 2 * login_attempt_window)
        clients = await _delete_unreferenced_clients(session, now - unused_client_retention)

    if pending or codes or tokens or attempts or clients:
        logger.info(
            "auth.cleanup.purged",
            extra={
                "pending_authorizations": pending,
                "authorization_codes": codes,
                "oauth_tokens": tokens,
                "login_attempts": attempts,
                "oauth_clients": clients,
            },
        )


async def _sweep_forever(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    token_retention: timedelta,
    login_attempt_window: timedelta,
    unused_client_retention: timedelta,
    cleanup_interval: timedelta,
) -> None:
    while True:
        try:
            await purge_expired_auth_rows(
                session_factory,
                token_retention=token_retention,
                login_attempt_window=login_attempt_window,
                unused_client_retention=unused_client_retention,
            )
        except Exception:
            logger.exception("auth.cleanup.failed")
        await asyncio.sleep(cleanup_interval.total_seconds())


@asynccontextmanager
async def cleanup_lifespan(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    token_retention: timedelta,
    login_attempt_window: timedelta,
    unused_client_retention: timedelta,
    cleanup_interval: timedelta,
) -> AsyncGenerator[None]:
    task = asyncio.create_task(
        _sweep_forever(
            session_factory,
            token_retention=token_retention,
            login_attempt_window=login_attempt_window,
            unused_client_retention=unused_client_retention,
            cleanup_interval=cleanup_interval,
        )
    )
    try:
        yield
    finally:
        _ = task.cancel()
        _ = await asyncio.gather(task, return_exceptions=True)
