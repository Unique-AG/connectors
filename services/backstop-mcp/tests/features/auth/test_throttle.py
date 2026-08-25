"""Failed-login throttling, at the storage layer and through the login form.

The point of the limit is that `POST /backstop/login` can't be used to test credentials against
Backstop, so the tests that matter most are the ones asserting Backstop is never called once the
budget is spent.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backstop_mcp.db import LoginAttempt, transaction
from backstop_mcp.features.auth.throttle import (
    MAX_USERNAME_LENGTH,
    ThrottleConfig,
    clear_failures,
    count_recent_failures,
    is_throttled,
    record_failure,
)

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]

_WINDOW = timedelta(minutes=15)


def _config(max_attempts: int = 3, window: timedelta = _WINDOW) -> ThrottleConfig:
    return ThrottleConfig(max_attempts=max_attempts, window=window)


async def _seed_attempt(
    session_factory: async_sessionmaker[AsyncSession], username: str, *, age: timedelta
) -> None:
    """Record one failed attempt `age` in the past, to place it inside or outside the window."""
    async with transaction(session_factory) as session:
        session.add(
            LoginAttempt(
                username=username,
                source_ip=None,
                attempted_at=datetime.now(UTC) - age,
            )
        )


class TestFailureCounting:
    @pytest.mark.asyncio
    async def test_counts_only_attempts_inside_the_window(self, db: DatabaseFixture) -> None:
        _, session_factory = db
        username = "throttle-window-user"
        await _seed_attempt(session_factory, username, age=timedelta(minutes=1))
        await _seed_attempt(session_factory, username, age=timedelta(minutes=14))
        # Outside a 15-minute window, so it must not count toward the limit.
        await _seed_attempt(session_factory, username, age=timedelta(minutes=16))

        assert await count_recent_failures(session_factory, username, window=_WINDOW) == 2

    @pytest.mark.asyncio
    async def test_counts_are_per_username(self, db: DatabaseFixture) -> None:
        """One account's failures must not throttle another — that would be a lockout vector."""
        _, session_factory = db
        await _seed_attempt(session_factory, "throttle-noisy-user", age=timedelta(minutes=1))
        await _seed_attempt(session_factory, "throttle-noisy-user", age=timedelta(minutes=1))

        assert (
            await count_recent_failures(session_factory, "throttle-quiet-user", window=_WINDOW) == 0
        )
        assert not await is_throttled(session_factory, "throttle-quiet-user", config=_config(1))


class TestThrottleDecision:
    @pytest.mark.asyncio
    async def test_allows_up_to_the_limit_then_blocks(self, db: DatabaseFixture) -> None:
        _, session_factory = db
        username = "throttle-boundary-user"
        config = _config(max_attempts=3)

        for _ in range(2):
            await record_failure(session_factory, username, source_ip="10.0.0.1")
        # Two failures against a limit of three: the third attempt is still allowed.
        assert not await is_throttled(session_factory, username, config=config)

        await record_failure(session_factory, username, source_ip="10.0.0.1")
        assert await is_throttled(session_factory, username, config=config)

    @pytest.mark.asyncio
    async def test_a_successful_login_clears_the_budget(self, db: DatabaseFixture) -> None:
        _, session_factory = db
        username = "throttle-cleared-user"
        config = _config(max_attempts=2)
        await record_failure(session_factory, username, source_ip=None)
        await record_failure(session_factory, username, source_ip=None)
        assert await is_throttled(session_factory, username, config=config)

        await clear_failures(session_factory, username)

        assert not await is_throttled(session_factory, username, config=config)

    @pytest.mark.asyncio
    async def test_clearing_one_username_leaves_others_alone(self, db: DatabaseFixture) -> None:
        _, session_factory = db
        await record_failure(session_factory, "throttle-keep-user", source_ip=None)
        await record_failure(session_factory, "throttle-drop-user", source_ip=None)

        await clear_failures(session_factory, "throttle-drop-user")

        assert (
            await count_recent_failures(session_factory, "throttle-keep-user", window=_WINDOW) == 1
        )
        assert (
            await count_recent_failures(session_factory, "throttle-drop-user", window=_WINDOW) == 0
        )

    @pytest.mark.asyncio
    async def test_the_window_expires_the_block(self, db: DatabaseFixture) -> None:
        """The limit bounds guessing rate, so it must lift on its own without an admin."""
        _, session_factory = db
        username = "throttle-expiring-user"
        config = _config(max_attempts=2)
        await _seed_attempt(session_factory, username, age=timedelta(minutes=20))
        await _seed_attempt(session_factory, username, age=timedelta(minutes=20))

        assert not await is_throttled(session_factory, username, config=config)

    @pytest.mark.asyncio
    async def test_records_the_source_ip_for_diagnosis(self, db: DatabaseFixture) -> None:
        """Stored but never enforced on — see `throttle.py` on why IP is not the key."""
        _, session_factory = db
        username = "throttle-ip-user"
        await record_failure(session_factory, username, source_ip="203.0.113.7")

        async with session_factory() as session:
            result = await session.execute(
                select(LoginAttempt.source_ip).where(LoginAttempt.username == username)
            )
            assert result.scalars().all() == ["203.0.113.7"]


class TestUsernameLengthGuard:
    def test_the_cap_admits_a_full_length_email(self) -> None:
        """320 = 64-char local part + '@' + 255-char domain, the practical email maximum."""
        assert MAX_USERNAME_LENGTH == 320
        assert len("a" * 64 + "@" + "b" * 255) == MAX_USERNAME_LENGTH
