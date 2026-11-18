import asyncio
from collections.abc import AsyncGenerator, Generator
from datetime import datetime
from datetime import timedelta
from datetime import UTC
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from pydantic import SecretStr
import pytest
from sqlalchemy import select
from testcontainers.community.postgres import PostgresContainer

from polixis_mcp.persistence import PostgresResponseCache
from polixis_mcp.persistence.database import create_engine
from polixis_mcp.persistence.database import DatabaseSettings
from polixis_mcp.persistence.models import ResponseCacheRow
from polixis_mcp.shared import CachedAnswer

_SERVICE_ROOT = Path(__file__).parent.parent


def _migrate(url: str) -> None:
    """Runs the migrations the chart's hook runs, and checks they match the models."""
    environment_before = os.environ.copy()
    os.environ["DB_URL"] = url
    try:
        config = Config(str(_SERVICE_ROOT / "alembic.ini"))
        command.upgrade(config, "head")
        command.check(config)
    finally:
        os.environ.clear()
        os.environ.update(environment_before)


@pytest.fixture(scope="session")
def database_url() -> Generator[str]:
    """`TEST_DB_URL` points the tests at a Postgres that is already running, for a machine
    without Docker; otherwise a container is started, as in CI.
    """
    provided = os.environ.get("TEST_DB_URL")
    if provided:
        _migrate(provided)
        yield provided
        return
    with PostgresContainer("postgres:17-alpine", driver=None) as postgres:
        url = postgres.get_connection_url()
        _migrate(url)
        yield url


@pytest.fixture
async def cache(database_url: str) -> AsyncGenerator[PostgresResponseCache]:
    settings = DatabaseSettings(
        url=SecretStr(database_url),
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )
    cache = PostgresResponseCache(create_engine(settings))
    await cache.setup()
    async with cache._engine.begin() as connection:
        await connection.exec_driver_sql("TRUNCATE polixis_response_cache")
    try:
        yield cache
    finally:
        await cache.close()


async def _keys_and_reads(cache: PostgresResponseCache) -> dict[str, int]:
    async with cache._engine.connect() as connection:
        rows = await connection.execute(select(ResponseCacheRow.key, ResponseCacheRow.reads))
    return {key: reads for key, reads in rows}


def _answer(size: int, *, cached_at: datetime | None = None) -> CachedAnswer:
    return CachedAnswer(cached_at=cached_at or datetime.now(UTC), body=b"x" * size)


async def test_returns_what_it_cached_and_counts_the_reads(
    cache: PostgresResponseCache,
) -> None:
    answer = _answer(10)
    await cache.put("graph", answer, ttl_seconds=60)

    read = [await cache.get("graph") for _ in range(2)]

    assert read == [answer, answer]
    assert await _keys_and_reads(cache) == {"graph": 2}


async def test_an_expired_answer_is_not_returned_and_the_cull_deletes_it(
    cache: PostgresResponseCache,
) -> None:
    an_hour_ago = datetime.now(UTC) - timedelta(hours=1)
    await cache.put("expired", _answer(10, cached_at=an_hour_ago), ttl_seconds=60)
    await cache.put("fresh", _answer(10), ttl_seconds=60)

    missed = await cache.get("expired")
    await cache.cull(max_bytes=1_000)

    assert missed is None
    assert await _keys_and_reads(cache) == {"fresh": 0}


async def test_the_cull_keeps_the_most_recently_read_answers_within_the_size(
    cache: PostgresResponseCache,
) -> None:
    for key in ("read-first", "never-read", "read-last"):
        await cache.put(key, _answer(100), ttl_seconds=60)
        await asyncio.sleep(0.01)
    await cache.get("read-first")
    await asyncio.sleep(0.01)
    await cache.get("read-last")

    await cache.cull(max_bytes=250)

    assert await _keys_and_reads(cache) == {"read-first": 1, "read-last": 1}


async def test_caching_the_same_key_again_replaces_the_answer(
    cache: PostgresResponseCache,
) -> None:
    await cache.put("search", _answer(10), ttl_seconds=60)
    newer = _answer(20)

    await cache.put("search", newer, ttl_seconds=60)

    assert await cache.get("search") == newer
