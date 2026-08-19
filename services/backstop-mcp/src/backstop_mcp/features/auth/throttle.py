"""Failed-login throttling for the hosted Backstop login form.

`POST /backstop/login` forwards a submitted username + personal API token to Backstop and reports
whether it authenticated. Anyone who can start an OAuth flow can mint a valid `request_id`, so
without a limit that endpoint is a credential-testing oracle against a third party's CRM.

**Keyed on username, not source IP.** This service runs behind an ingress, so
`request.client.host` is the ingress's address for every caller — an IP limit on it would let one
attacker lock out every user. The alternative, trusting `X-Forwarded-For`, is client-spoofable and
therefore worthless as a control: an attacker just varies the header. A per-username limit is the
one that actually binds, because the attacker cannot choose a different username and still be
attacking the same account. Spraying across many usernames stays possible, but each account gets
at most `max_attempts` guesses per window, which is the property that matters.

Storage is a row per failed attempt (see `db/models.LoginAttempt`) so the sliding window is
shared across replicas with no coordination. The check-then-insert path is not atomic, so a
concurrent burst can briefly exceed `max_attempts` by a few; that is acceptable for a
credential-guessing bound, not a hard quota.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import ClassVar

from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backstop_mcp.db import LoginAttempt, read_session, transaction

logger = logging.getLogger(__name__)

# Submitted usernames are attacker-controlled and land in a `text` column. Backstop usernames are
# email addresses or short handles, so anything past this is not a real username — rejected before
# it can be stored, so the throttle table can't be used to write unbounded rows.
MAX_USERNAME_LENGTH = 320


class ThrottleConfig(BaseModel):
    """The limit to apply. Derived from `AuthConfig` at the composition root."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    max_attempts: int
    window: timedelta


async def count_recent_failures(
    session_factory: async_sessionmaker[AsyncSession],
    username: str,
    *,
    window: timedelta,
) -> int:
    since = datetime.now(UTC) - window
    async with read_session(session_factory) as session:
        result = await session.execute(
            select(func.count())
            .select_from(LoginAttempt)
            .where(LoginAttempt.username == username, LoginAttempt.attempted_at >= since)
        )
        return result.scalar_one()


async def is_throttled(
    session_factory: async_sessionmaker[AsyncSession],
    username: str,
    *,
    config: ThrottleConfig,
) -> bool:
    """Whether `username` has already used up its attempts for the current window."""
    failures = await count_recent_failures(session_factory, username, window=config.window)
    if failures < config.max_attempts:
        return False
    logger.warning(
        "auth.login.throttled",
        extra={
            "failures": failures,
            "max_attempts": config.max_attempts,
            "window_minutes": int(config.window.total_seconds() // 60),
        },
    )
    return True


async def record_failure(
    session_factory: async_sessionmaker[AsyncSession],
    username: str,
    *,
    source_ip: str | None,
) -> None:
    """Record one failed attempt. `source_ip` is stored for diagnosis, never rate-limited on."""
    async with transaction(session_factory) as session:
        session.add(
            LoginAttempt(username=username, source_ip=source_ip, attempted_at=datetime.now(UTC))
        )


async def clear_failures(session_factory: async_sessionmaker[AsyncSession], username: str) -> None:
    """Drop a username's failed attempts after it authenticates successfully.

    So two typos followed by a correct token leaves no residue — the limit exists to bound
    guessing, not to punish a user who eventually got in.
    """
    async with transaction(session_factory) as session:
        await session.execute(delete(LoginAttempt).where(LoginAttempt.username == username))
