import asyncio
from collections.abc import AsyncGenerator, Generator
from contextlib import contextmanager
from datetime import datetime
from datetime import timedelta
from datetime import UTC
import os
from pathlib import Path
import uuid

from alembic import command
from alembic.config import Config
import httpx2
from key_value.aio.errors import StoreSetupError
from key_value.aio.stores.postgresql import PostgreSQLStore
from pydantic import SecretStr
import pytest
from sqlalchemy import func
from sqlalchemy import insert
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

from polixis_mcp.persistence import postgres_store
from polixis_mcp.persistence import PostgresResponseCache
from polixis_mcp.persistence import PostgresSignInStateTable
from polixis_mcp.persistence import StoreSettings
from polixis_mcp.persistence.database import create_database
from polixis_mcp.persistence.database import Database
from polixis_mcp.persistence.database import DatabaseSettings
from polixis_mcp.persistence.database import open_database
from polixis_mcp.persistence.models import KeyValueRow
from polixis_mcp.persistence.models import ResponseCacheRow
from polixis_mcp.shared import CachedAnswer

_SERVICE_ROOT = Path(__file__).parent.parent


@contextmanager
def _alembic(url: str) -> Generator[Config]:
    """The configuration the chart's hook runs `alembic` with, against `url`."""
    environment_before = os.environ.copy()
    os.environ["DB_URL"] = url
    try:
        yield Config(str(_SERVICE_ROOT / "alembic.ini"))
    finally:
        os.environ.clear()
        os.environ.update(environment_before)


def _migrate(url: str) -> None:
    """Runs the migrations the chart's hook runs, and checks they match the models."""
    with _alembic(url) as config:
        command.upgrade(config, "head")
        command.check(config)


@pytest.fixture(scope="session")
def server_url() -> Generator[str]:
    """The Postgres server the tests make their own databases on. `TEST_DB_URL` names one that
    is already running, for a machine without Docker: the tests never touch the database it
    names, only the ones they create and drop beside it, which needs `CREATEDB`. Otherwise a
    container is started, as in CI.
    """
    provided = os.environ.get("TEST_DB_URL")
    if provided:
        yield provided
        return
    with PostgresContainer("postgres:17-alpine", driver=None) as postgres:
        yield postgres.get_connection_url()


@contextmanager
def _new_database(server_url: str) -> Generator[str]:
    """An empty database of the test run's own, dropped on exit."""
    name = f"polixis_mcp_test_{uuid.uuid4().hex[:12]}"
    asyncio.run(
        _run_outside_a_transaction(server_url, f'CREATE DATABASE "{name}" TEMPLATE template0')
    )
    try:
        yield str(httpx2.URL(server_url).copy_with(path=f"/{name}"))
    finally:
        asyncio.run(_run_outside_a_transaction(server_url, f'DROP DATABASE "{name}" WITH (FORCE)'))


async def _run_outside_a_transaction(server_url: str, statement: str) -> None:
    engine = _engine(server_url).execution_options(isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.exec_driver_sql(statement)
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def database_url(server_url: str) -> Generator[str]:
    """The migrated database the tests share."""
    with _new_database(server_url) as url:
        _migrate(url)
        yield url


@pytest.fixture
async def database(database_url: str) -> AsyncGenerator[Database]:
    database = create_database(
        DatabaseSettings(
            url=SecretStr(database_url),
            _env_file=None,  # pyright: ignore[reportCallIssue]
        )
    )
    async with open_database(database):
        async with database.begin() as session:
            await session.execute(text("TRUNCATE polixis_response_cache, kv_store"))
        yield database


@pytest.fixture
def cache(database: Database) -> PostgresResponseCache:
    return PostgresResponseCache(database)


async def _keys_and_reads(database: Database) -> dict[str, int]:
    async with database() as session:
        rows = await session.execute(select(ResponseCacheRow.key, ResponseCacheRow.reads))
    return {key: reads for key, reads in rows}


def _answer(size: int, *, cached_at: datetime | None = None) -> CachedAnswer:
    return CachedAnswer(cached_at=cached_at or datetime.now(UTC), body=b"x" * size)


async def test_returns_what_it_cached_and_counts_the_reads(
    cache: PostgresResponseCache, database: Database
) -> None:
    answer = _answer(10)
    await cache.put("graph", answer, ttl_seconds=60)

    read = [await cache.get("graph") for _ in range(2)]

    assert read == [answer, answer]
    assert await _keys_and_reads(database) == {"graph": 2}


async def test_an_expired_answer_is_not_returned_and_the_cull_deletes_it(
    cache: PostgresResponseCache, database: Database
) -> None:
    an_hour_ago = datetime.now(UTC) - timedelta(hours=1)
    await cache.put("expired", _answer(10, cached_at=an_hour_ago), ttl_seconds=60)
    await cache.put("fresh", _answer(10), ttl_seconds=60)

    missed = await cache.get("expired")
    await cache.cull(max_bytes=1_000)

    assert missed is None
    assert await _keys_and_reads(database) == {"fresh": 0}


async def test_the_cull_keeps_the_most_recently_read_answers_within_the_size(
    cache: PostgresResponseCache, database: Database
) -> None:
    for key in ("read-first", "never-read", "read-last"):
        await cache.put(key, _answer(100), ttl_seconds=60)
        await asyncio.sleep(0.01)
    await cache.get("read-first")
    await asyncio.sleep(0.01)
    await cache.get("read-last")

    await cache.cull(max_bytes=250)

    assert await _keys_and_reads(database) == {"read-first": 1, "read-last": 1}


async def test_the_cull_takes_a_size_past_what_an_integer_holds(
    cache: PostgresResponseCache, database: Database
) -> None:
    await cache.put("graph", _answer(10), ttl_seconds=60)

    await cache.cull(max_bytes=3_000_000_000)

    assert await _keys_and_reads(database) == {"graph": 0}


async def test_the_cull_keeps_an_answer_read_while_it_ranked_the_answers(
    cache: PostgresResponseCache, database: Database
) -> None:
    for key in ("older", "newer"):
        await cache.put(key, _answer(100), ttl_seconds=60)
        await asyncio.sleep(0.01)

    async with database.begin() as session:
        _ = await session.execute(
            update(ResponseCacheRow)
            .where(ResponseCacheRow.key == "older")
            .values(last_used_at=func.now())
        )
        reader = await session.scalar(select(func.pg_backend_pid()))
        culling = asyncio.create_task(cache.cull(max_bytes=150))
        await _until_blocked_by(database, reader)
    await culling

    assert set(await _keys_and_reads(database)) == {"older", "newer"}


async def _until_blocked_by(database: Database, pid: int | None) -> None:
    """Waits until another backend waits on a lock `pid` holds, as the cull's delete does."""
    blocked = text("SELECT count(*) FROM pg_stat_activity WHERE :pid = ANY(pg_blocking_pids(pid))")
    async with asyncio.timeout(5):
        while True:
            async with database() as session:
                if await session.scalar(blocked, {"pid": pid}):
                    return
            await asyncio.sleep(0.01)


async def test_caching_the_same_key_again_replaces_the_answer(
    cache: PostgresResponseCache, database: Database
) -> None:
    await cache.put("search", _answer(10), ttl_seconds=60)
    await cache.get("search")
    newer = _answer(20)

    await cache.put("search", newer, ttl_seconds=60)

    assert await cache.get("search") == newer
    assert await _keys_and_reads(database) == {"search": 1}


def _store(database_url: str) -> PostgreSQLStore:
    return postgres_store(
        StoreSettings(
            url=SecretStr(database_url),
            _env_file=None,  # pyright: ignore[reportCallIssue]
        )
    )


async def test_the_key_value_store_keeps_its_entries_in_the_migrated_table(
    database_url: str,
) -> None:
    store = _store(database_url)
    await store.setup()
    try:
        await store.put("state", {"step": 1}, collection="sign-in", ttl=60)

        assert await store.get("state", collection="sign-in") == {"step": 1}
    finally:
        await store.close()


async def _save_sign_in_state(database_url: str) -> None:
    """As the server did before the migrations: its store makes `kv_store` when there is none."""
    async with PostgreSQLStore(url=database_url, table_name="kv_store") as store:
        await store.setup()
        await store.put("state", {"step": 1}, collection="sign-in", ttl=60)


def test_the_migration_keeps_the_table_and_rows_the_store_made_before_it(
    server_url: str,
) -> None:
    """The server made `kv_store` itself on first use before, so a deployment that never ran a
    migration holds it, with sign-in state in it, before the migration that makes it runs.
    """
    with _new_database(server_url) as url, _alembic(url) as config:
        asyncio.run(_save_sign_in_state(url))

        command.upgrade(config, "head")
        command.check(config)
        kept = asyncio.run(_sign_in_state(url))

    assert kept == {"step": 1}


def test_a_downgrade_keeps_the_sign_in_state(server_url: str) -> None:
    """The server before the migrations reads the sign-in state from `kv_store`."""
    with _new_database(server_url) as url, _alembic(url) as config:
        command.upgrade(config, "head")
        asyncio.run(_save_sign_in_state(url))

        command.downgrade(config, "base")
        kept = asyncio.run(_sign_in_state(url))
        tables = asyncio.run(_tables(url))

    assert kept == {"step": 1}
    assert tables == ["alembic_version", "kv_store"]


async def _tables(database_url: str) -> list[str]:
    engine = _engine(database_url)
    try:
        async with engine.connect() as connection:
            names = await connection.scalars(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1")
            )
            return list(names)
    finally:
        await engine.dispose()


async def _sign_in_state(database_url: str) -> dict[str, object] | None:
    store = _store(database_url)
    try:
        return await store.get("state", collection="sign-in")
    finally:
        await store.close()


def test_the_key_value_store_does_not_make_its_table(server_url: str) -> None:
    with (
        _new_database(server_url) as unmigrated,
        pytest.raises(StoreSetupError, match="does not exist"),
    ):
        asyncio.run(_store(unmigrated).setup())


async def test_the_cull_deletes_the_expired_sign_in_state(database: Database) -> None:
    now = datetime.now(UTC)
    async with database.begin() as session:
        await session.execute(
            insert(KeyValueRow),
            [
                {"collection": "sign-in", "key": "expired", "value": {}, "expires_at": now},
                {"collection": "sign-in", "key": "lasting", "value": {}, "expires_at": None},
                {
                    "collection": "sign-in",
                    "key": "fresh",
                    "value": {},
                    "expires_at": now + timedelta(hours=1),
                },
            ],
        )

    await PostgresSignInStateTable(database).cull()

    async with database() as session:
        keys = await session.scalars(select(KeyValueRow.key).order_by(KeyValueRow.key))
    assert keys.all() == ["fresh", "lasting"]


def _engine(database_url: str) -> AsyncEngine:
    settings = DatabaseSettings(
        url=SecretStr(database_url),
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )
    return create_async_engine(settings.connection_url, connect_args=dict(settings.connect_args))
