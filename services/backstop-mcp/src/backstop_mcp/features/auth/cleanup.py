"""Periodic deletion of auth rows that can no longer be used.

Without this, three tables grow without bound: abandoned logins leave `pending_authorizations`
rows, unexchanged codes leave `authorization_codes` rows, and — the one that actually
accumulates — every refresh rotation adds an `oauth_tokens` row that is never removed. With a
15-minute access-token TTL that is roughly 2,900 rows per active user per month, all of them in
the table `load_access_token` queries on every single MCP request.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import delete, or_, select
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backstop_mcp.config import AuthConfig
from backstop_mcp.db.engine import transaction
from backstop_mcp.db.models import (
    AuthorizationCode,
    LoginAttempt,
    OAuthToken,
    PendingAuthorization,
)
from backstop_mcp.logging import get_logger

logger = get_logger(__name__)


def _deleted(result: Result[tuple[object, ...]]) -> int:
    """How many rows a DELETE removed. Not on SQLAlchemy's async-facing `Result` stub."""
    return cast("int", result.rowcount)  # pyright: ignore[reportAttributeAccessIssue]


async def _delete_expired_pending(session: AsyncSession, now: datetime) -> int:
    """Drop in-flight authorizations whose login form was never submitted in time."""
    result = await session.execute(
        delete(PendingAuthorization).where(PendingAuthorization.expires_at < now)
    )
    return _deleted(result)


async def _delete_expired_codes(session: AsyncSession, now: datetime) -> int:
    """Drop authorization codes never exchanged for tokens.

    `expires_at` is a POSIX timestamp here (mirroring the MCP SDK's own `AuthorizationCode`),
    not a `datetime` like the other two tables.
    """
    result = await session.execute(
        delete(AuthorizationCode).where(AuthorizationCode.expires_at < now.timestamp())
    )
    return _deleted(result)


async def _delete_old_token_families(session: AsyncSession, cutoff: datetime) -> int:
    """Drop token families whose every member expired before `cutoff`.

    Deleting by *family* rather than by row is what makes this safe: `rotated_from` is a
    self-referential foreign key, and a row's descendants always share its `family_id` (see
    `provider.exchange_refresh_token`), so no surviving row can reference a deleted one. Row-wise
    deletion would strand the newest token pointing at a purged ancestor.
    """
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
    """Drop failed-login records older than any throttling window still cares about.

    `auth/throttle.py` only ever reads attempts inside its window, so anything older is dead
    weight — and the table takes a row per failed attempt, which is the one place an attacker
    can drive row growth.
    """
    result = await session.execute(delete(LoginAttempt).where(LoginAttempt.attempted_at < cutoff))
    return _deleted(result)


async def purge_expired_auth_rows(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    token_retention: timedelta,
    login_attempt_window: timedelta,
) -> None:
    """Run one sweep. Safe to run concurrently on several replicas — every delete is idempotent."""
    now = datetime.now(UTC)
    async with transaction(session_factory) as session:
        pending = await _delete_expired_pending(session, now)
        codes = await _delete_expired_codes(session, now)
        tokens = await _delete_old_token_families(session, now - token_retention)
        # Kept for a couple of windows rather than exactly one, so a sweep landing mid-window
        # can't shorten anyone's effective limit.
        attempts = await _delete_old_login_attempts(session, now - 2 * login_attempt_window)

    if pending or codes or tokens or attempts:
        logger.info(
            "auth.cleanup.purged",
            pending_authorizations=pending,
            authorization_codes=codes,
            oauth_tokens=tokens,
            login_attempts=attempts,
        )


async def _sweep_forever(
    session_factory: async_sessionmaker[AsyncSession], config: AuthConfig
) -> None:
    """Sweep on start, then once per `config.cleanup_interval`.

    A failed sweep is logged and retried on the next tick rather than killing the task: nothing
    downstream depends on it having run, and an unreachable database already fails `/probe`.
    """
    while True:
        try:
            await purge_expired_auth_rows(
                session_factory,
                token_retention=config.token_retention,
                login_attempt_window=config.login_attempt_window,
            )
        except Exception:
            logger.exception("auth.cleanup.failed")
        await asyncio.sleep(config.cleanup_interval.total_seconds())


@asynccontextmanager
async def cleanup_lifespan(
    session_factory: async_sessionmaker[AsyncSession], config: AuthConfig
) -> AsyncGenerator[None, None]:
    """Run the sweep loop in the background for the lifetime of the app."""
    task = asyncio.create_task(_sweep_forever(session_factory, config))
    try:
        yield
    finally:
        _ = task.cancel()
        # Await so the cancelled task can't outlive the app or go unretrieved.
        _ = await asyncio.gather(task, return_exceptions=True)
