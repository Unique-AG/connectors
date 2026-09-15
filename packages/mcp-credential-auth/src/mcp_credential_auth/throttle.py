import logging
from datetime import UTC, datetime, timedelta
from typing import ClassVar

from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mcp_credential_auth.database import read_session, transaction
from mcp_credential_auth.models import LoginAttempt

logger = logging.getLogger(__name__)

MAX_USERNAME_LENGTH = 320


class ThrottleConfig(BaseModel):
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
    async with transaction(session_factory) as session:
        session.add(
            LoginAttempt(username=username, source_ip=source_ip, attempted_at=datetime.now(UTC))
        )


async def clear_failures(session_factory: async_sessionmaker[AsyncSession], username: str) -> None:
    async with transaction(session_factory) as session:
        await session.execute(delete(LoginAttempt).where(LoginAttempt.username == username))
