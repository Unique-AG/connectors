import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mcp_credential_auth import (
    MAX_USERNAME_LENGTH,
    LoginAttempt,
    LoginThrottleConfig,
    count_recent_login_failures,
    discard_login_attempt,
    finalize_login_failure,
    record_login_success,
    reserve_login_attempt,
    transaction,
)

_WINDOW = timedelta(minutes=15)


def _config(max_attempts: int = 3, window: timedelta = _WINDOW) -> LoginThrottleConfig:
    return LoginThrottleConfig(max_attempts=max_attempts, window=window)


async def _seed_attempt(
    session_factory: async_sessionmaker[AsyncSession], username: str, *, age: timedelta
) -> None:
    async with transaction(session_factory) as session:
        session.add(
            LoginAttempt(
                username=username,
                source_ip=None,
                attempted_at=datetime.now(UTC) - age,
            )
        )


async def test_counts_only_attempts_inside_the_window(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    username = "throttle-window-user"
    await _seed_attempt(session_factory, username, age=timedelta(minutes=1))
    await _seed_attempt(session_factory, username, age=timedelta(minutes=14))
    await _seed_attempt(session_factory, username, age=timedelta(minutes=16))

    assert await count_recent_login_failures(session_factory, username, window=_WINDOW) == 2


async def test_counts_are_per_username(session_factory: async_sessionmaker[AsyncSession]) -> None:
    await _seed_attempt(session_factory, "throttle-noisy-user", age=timedelta(minutes=1))
    await _seed_attempt(session_factory, "throttle-noisy-user", age=timedelta(minutes=1))

    assert (
        await count_recent_login_failures(session_factory, "throttle-quiet-user", window=_WINDOW)
        == 0
    )


async def test_allows_up_to_the_limit_then_blocks(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    username = "throttle-boundary-user"
    config = _config(max_attempts=3)

    for _ in range(3):
        attempt_id = await reserve_login_attempt(
            session_factory, username, source_ip="10.0.0.1", config=config
        )
        assert attempt_id is not None
        await finalize_login_failure(session_factory, attempt_id)

    assert (
        await reserve_login_attempt(session_factory, username, source_ip="10.0.0.1", config=config)
        is None
    )


async def test_concurrent_reservations_cannot_exceed_the_limit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    reservations = await asyncio.gather(
        *(
            reserve_login_attempt(
                session_factory,
                "throttle-concurrent-user",
                source_ip=None,
                config=_config(max_attempts=2),
            )
            for _ in range(5)
        )
    )

    assert sum(reservation is not None for reservation in reservations) == 2


async def test_discarding_a_reservation_restores_the_budget(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    username = "throttle-discard-user"
    reservation = await reserve_login_attempt(
        session_factory, username, source_ip=None, config=_config(max_attempts=1)
    )
    assert reservation is not None
    assert (
        await reserve_login_attempt(
            session_factory, username, source_ip=None, config=_config(max_attempts=1)
        )
        is None
    )

    await discard_login_attempt(session_factory, reservation)

    assert (
        await reserve_login_attempt(
            session_factory, username, source_ip=None, config=_config(max_attempts=1)
        )
        is not None
    )


async def test_success_preserves_other_pending_reservations(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    username = "throttle-pending-user"
    successful = await reserve_login_attempt(
        session_factory, username, source_ip=None, config=_config()
    )
    pending = await reserve_login_attempt(
        session_factory, username, source_ip=None, config=_config()
    )
    assert successful is not None
    assert pending is not None

    await record_login_success(session_factory, username, attempt_id=successful)
    await finalize_login_failure(session_factory, pending)

    assert await count_recent_login_failures(session_factory, username, window=_WINDOW) == 1


async def test_a_successful_login_clears_the_budget(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    username = "throttle-cleared-user"
    config = _config(max_attempts=2)
    for _ in range(2):
        attempt_id = await reserve_login_attempt(
            session_factory, username, source_ip=None, config=config
        )
        assert attempt_id is not None
        await finalize_login_failure(session_factory, attempt_id)

    successful_attempt_id = await reserve_login_attempt(
        session_factory, username, source_ip=None, config=_config(max_attempts=3)
    )
    assert successful_attempt_id is not None
    await record_login_success(session_factory, username, attempt_id=successful_attempt_id)

    assert (
        await reserve_login_attempt(session_factory, username, source_ip=None, config=config)
        is not None
    )


async def test_clearing_one_username_leaves_others_alone(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    for username in ("throttle-keep-user", "throttle-drop-user"):
        attempt_id = await reserve_login_attempt(
            session_factory, username, source_ip=None, config=_config()
        )
        assert attempt_id is not None
        await finalize_login_failure(session_factory, attempt_id)

    successful_attempt_id = await reserve_login_attempt(
        session_factory,
        "throttle-drop-user",
        source_ip=None,
        config=_config(),
    )
    assert successful_attempt_id is not None
    await record_login_success(
        session_factory,
        "throttle-drop-user",
        attempt_id=successful_attempt_id,
    )

    assert (
        await count_recent_login_failures(session_factory, "throttle-keep-user", window=_WINDOW)
        == 1
    )
    assert (
        await count_recent_login_failures(session_factory, "throttle-drop-user", window=_WINDOW)
        == 0
    )


async def test_the_window_expires_the_block(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    username = "throttle-expiring-user"
    config = _config(max_attempts=2)
    await _seed_attempt(session_factory, username, age=timedelta(minutes=20))
    await _seed_attempt(session_factory, username, age=timedelta(minutes=20))

    assert (
        await reserve_login_attempt(session_factory, username, source_ip=None, config=config)
        is not None
    )


async def test_records_the_source_ip_for_diagnosis(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    username = "throttle-ip-user"
    attempt_id = await reserve_login_attempt(
        session_factory, username, source_ip="203.0.113.7", config=_config()
    )
    assert attempt_id is not None

    async with session_factory() as session:
        result = await session.execute(
            select(LoginAttempt.source_ip).where(LoginAttempt.username == username)
        )
        assert result.scalars().all() == ["203.0.113.7"]


def test_the_cap_admits_a_full_length_email() -> None:
    assert MAX_USERNAME_LENGTH == 320
    assert len("a" * 64 + "@" + "b" * 255) == MAX_USERNAME_LENGTH
