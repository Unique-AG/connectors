import os
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]

_SERVICE_ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer]:
    """Start a PostgreSQL container (once per test session) and apply migrations against it.

    `db/migrations/env.py` builds its connection URL from `DatabaseConfig()`, which reads
    `DB_URL` from the environment — so migrations are pointed at the test container by
    setting that env var directly (rather than via `Config.set_main_option`, which
    `env.py` would immediately overwrite).
    """
    with PostgresContainer("postgres:17-alpine") as postgres:
        url = postgres.get_connection_url().replace("+psycopg2", "+asyncpg")
        previous_db_url = os.environ.get("DB_URL")
        os.environ["DB_URL"] = url
        try:
            command.upgrade(Config(str(_SERVICE_ROOT / "alembic.ini")), "head")
        finally:
            if previous_db_url is None:
                os.environ.pop("DB_URL", None)
            else:
                os.environ["DB_URL"] = previous_db_url
        yield postgres


@pytest.fixture
async def db(postgres_container: PostgresContainer) -> AsyncGenerator[DatabaseFixture]:
    """Create engine and session factory, dispose on cleanup.

    The underlying Postgres container is shared (and its data persists) across every test
    in the session — rows aren't reset between tests or files. Use IDs that are unique across
    the whole test suite (a prefix per test file, or a random uuid), not just within one file.
    """
    from backstop_mcp.config import DatabaseConfig
    from backstop_mcp.db.engine import create_engine, create_session_factory

    url = postgres_container.get_connection_url().replace("+psycopg2", "")
    config = DatabaseConfig(url=url)
    engine = create_engine(config)
    factory = create_session_factory(engine)
    yield engine, factory
    await engine.dispose()
