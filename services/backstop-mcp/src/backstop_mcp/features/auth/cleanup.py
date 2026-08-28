"""Periodic deletion of auth rows that can no longer be used.

Without this, four tables grow without bound: abandoned logins leave `pending_authorizations`
rows, unexchanged codes leave `authorization_codes` rows, dynamic client registration leaves
`oauth_clients` rows, and — the one that actually accumulates — every refresh rotation adds an
`oauth_tokens` row that is never removed. With a 15-minute access-token TTL that is roughly
2,900 rows per active user per month, all of them in the table `load_access_token` queries on
every single MCP request. (`login_attempts` is swept too, but it is the throttle's own storage
rather than something the OAuth flow leaves behind.)

Sweep order matters: `oauth_clients` is only removable once nothing references it, so the client
sweep runs last, after the three child tables have given up their expired rows in the same
transaction.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import delete, or_, select
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backstop_mcp.config import AuthConfig
from backstop_mcp.db import (
    AuthorizationCode,
    LoginAttempt,
    OAuthClient,
    OAuthToken,
    PendingAuthorization,
    transaction,
)

logger = logging.getLogger(__name__)


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


async def _delete_unreferenced_clients(session: AsyncSession, cutoff: datetime) -> int:
    """Drop registered clients that nothing references any more.

    Client registration is open (RFC 7591), so this is the one table an unauthenticated caller
    can grow directly, and nothing else ever removed a row from it.

    All three child tables carry a foreign key to `client_id`, so a client is only removable once
    the sweeps above have cleared its last pending authorization, code and token family — which is
    why this runs last, and why the `not_in` guards are per-table rather than one union: each is a
    plain anti-join the planner can satisfy from the child table directly. A client in active use
    always has a live token row and so never matches.

    The `created_at` floor is what keeps a client that registered moments ago from being swept
    before it has finished its first authorization round trip, when it legitimately has no
    children yet.
    """
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
    """Run one sweep. Safe to run concurrently on several replicas — every delete is idempotent."""
    now = datetime.now(UTC)
    async with transaction(session_factory) as session:
        pending = await _delete_expired_pending(session, now)
        codes = await _delete_expired_codes(session, now)
        tokens = await _delete_old_token_families(session, now - token_retention)
        # Kept for a couple of windows rather than exactly one, so a sweep landing mid-window
        # can't shorten anyone's effective limit.
        attempts = await _delete_old_login_attempts(session, now - 2 * login_attempt_window)
        # Last: the three deletes above are what make a client unreferenced, and doing this in
        # the same transaction means one sweep reclaims a client whose final token just expired
        # rather than leaving it for the next one.
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
    session_factory: async_sessionmaker[AsyncSession], config: AuthConfig
) -> None:
    """Sweep on start, then once per `config.cleanup_interval`.

    A failed sweep is logged and retried on the next tick rather than killing the task: nothing
    downstream depends on it having run, and an unreachable database already fails `/ready`.
    """
    while True:
        try:
            await purge_expired_auth_rows(
                session_factory,
                token_retention=config.token_retention,
                login_attempt_window=config.login_attempt_window,
                unused_client_retention=config.unused_client_retention,
            )
        except Exception:
            logger.exception("auth.cleanup.failed")
        await asyncio.sleep(config.cleanup_interval.total_seconds())


@asynccontextmanager
async def cleanup_lifespan(
    session_factory: async_sessionmaker[AsyncSession], config: AuthConfig
) -> AsyncGenerator[None]:
    """Run the sweep loop in the background for the lifetime of the app."""
    task = asyncio.create_task(_sweep_forever(session_factory, config))
    try:
        yield
    finally:
        _ = task.cancel()
        # Await so the cancelled task can't outlive the app or go unretrieved.
        _ = await asyncio.gather(task, return_exceptions=True)
