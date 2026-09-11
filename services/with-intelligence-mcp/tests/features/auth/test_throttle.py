"""Failed-login throttling. Keyed on username — see `auth/throttle.py` for why not on IP."""

import uuid
from datetime import UTC, datetime, timedelta

from tests.conftest import DatabaseFixture
from with_intelligence_mcp.db import LoginAttempt, transaction
from with_intelligence_mcp.features.auth import ThrottleConfig
from with_intelligence_mcp.features.auth.throttle import (
    clear_failures,
    count_recent_failures,
    is_throttled,
    record_failure,
)

CONFIG = ThrottleConfig(max_attempts=3, window=timedelta(minutes=15))


def _username(tag: str) -> str:
    return f"throttle-{tag}-{uuid.uuid4().hex[:8]}"


class TestCounting:
    async def test_a_fresh_username_has_no_failures(self, db: DatabaseFixture) -> None:
        _, factory = db
        assert await count_recent_failures(factory, _username("fresh"), window=CONFIG.window) == 0

    async def test_failures_accumulate(self, db: DatabaseFixture) -> None:
        _, factory = db
        username = _username("accumulate")
        for _ in range(2):
            await record_failure(factory, username, source_ip="10.0.0.1")
        assert await count_recent_failures(factory, username, window=CONFIG.window) == 2

    async def test_failures_outside_the_window_do_not_count(self, db: DatabaseFixture) -> None:
        _, factory = db
        username = _username("expired")
        async with transaction(factory) as session:
            session.add(
                LoginAttempt(
                    username=username,
                    source_ip=None,
                    attempted_at=datetime.now(UTC) - timedelta(hours=2),
                )
            )
        assert await count_recent_failures(factory, username, window=CONFIG.window) == 0


class TestThrottling:
    async def test_under_the_limit_is_not_throttled(self, db: DatabaseFixture) -> None:
        _, factory = db
        username = _username("under")
        for _ in range(CONFIG.max_attempts - 1):
            await record_failure(factory, username, source_ip=None)
        assert await is_throttled(factory, username, config=CONFIG) is False

    async def test_at_the_limit_is_throttled(self, db: DatabaseFixture) -> None:
        _, factory = db
        username = _username("at-limit")
        for _ in range(CONFIG.max_attempts):
            await record_failure(factory, username, source_ip=None)
        assert await is_throttled(factory, username, config=CONFIG) is True

    async def test_one_username_does_not_throttle_another(self, db: DatabaseFixture) -> None:
        """The property that makes a username limit usable: no cross-user lockout."""
        _, factory = db
        attacked, bystander = _username("attacked"), _username("bystander")
        for _ in range(CONFIG.max_attempts):
            await record_failure(factory, attacked, source_ip=None)
        assert await is_throttled(factory, bystander, config=CONFIG) is False

    async def test_a_success_clears_the_budget(self, db: DatabaseFixture) -> None:
        """The limit bounds guessing; it does not punish a user who eventually gets in."""
        _, factory = db
        username = _username("cleared")
        for _ in range(CONFIG.max_attempts):
            await record_failure(factory, username, source_ip=None)
        await clear_failures(factory, username)
        assert await is_throttled(factory, username, config=CONFIG) is False

    async def test_clearing_one_username_leaves_others(self, db: DatabaseFixture) -> None:
        _, factory = db
        kept, cleared = _username("kept"), _username("cleared-only")
        await record_failure(factory, kept, source_ip=None)
        await record_failure(factory, cleared, source_ip=None)
        await clear_failures(factory, cleared)
        assert await count_recent_failures(factory, kept, window=CONFIG.window) == 1
        assert await count_recent_failures(factory, cleared, window=CONFIG.window) == 0
