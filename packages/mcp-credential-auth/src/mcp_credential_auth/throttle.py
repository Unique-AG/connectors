import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import ClassVar

from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mcp_credential_auth.database import read_session, transaction
from mcp_credential_auth.models import LoginAttempt

logger = logging.getLogger(__name__)

MAX_USERNAME_LENGTH = 320


class LoginThrottleConfig(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    max_attempts: int
    window: timedelta


async def count_recent_login_failures(
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


async def reserve_login_attempt(
    session_factory: async_sessionmaker[AsyncSession],
    username: str,
    *,
    source_ip: str | None,
    config: LoginThrottleConfig,
) -> uuid.UUID | None:
    now = datetime.now(UTC)
    async with transaction(session_factory) as session:
        if session.bind.dialect.name == "postgresql":
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:username, 0))"),
                {"username": username},
            )
        result = await session.execute(
            select(func.count())
            .select_from(LoginAttempt)
            .where(
                LoginAttempt.username == username,
                LoginAttempt.attempted_at >= now - config.window,
            )
        )
        failures = result.scalar_one()
        if failures >= config.max_attempts:
            logger.warning(
                "auth.login.throttled",
                extra={
                    "failures": failures,
                    "max_attempts": config.max_attempts,
                    "window_minutes": int(config.window.total_seconds() // 60),
                },
            )
            return None
        attempt_id = uuid.uuid4()
        session.add(
            LoginAttempt(
                id=attempt_id,
                username=username,
                source_ip=source_ip,
                attempted_at=now,
                pending=True,
            )
        )
        return attempt_id


async def finalize_login_failure(
    session_factory: async_sessionmaker[AsyncSession], attempt_id: uuid.UUID
) -> None:
    async with transaction(session_factory) as session:
        await session.execute(
            update(LoginAttempt).where(LoginAttempt.id == attempt_id).values(pending=False)
        )


async def discard_login_attempt(
    session_factory: async_sessionmaker[AsyncSession], attempt_id: uuid.UUID
) -> None:
    async with transaction(session_factory) as session:
        await session.execute(delete(LoginAttempt).where(LoginAttempt.id == attempt_id))


async def record_login_success(
    session_factory: async_sessionmaker[AsyncSession],
    username: str,
    *,
    attempt_id: uuid.UUID,
) -> None:
    async with transaction(session_factory) as session:
        await session.execute(
            delete(LoginAttempt).where(
                LoginAttempt.username == username,
                or_(LoginAttempt.pending.is_(False), LoginAttempt.id == attempt_id),
            )
        )
