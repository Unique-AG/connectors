import os
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer

from backstop_mcp.server.runtime import reset_services

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]

_SERVICE_ROOT = Path(__file__).parent.parent


@pytest.fixture(autouse=True)
async def _reset_runtime() -> AsyncGenerator[None]:
    """Drop the process-wide services between tests.

    One hook, because there is one holder (`runtime._services`). Necessary because each test
    function runs on its own event loop (`asyncio_default_fixture_loop_scope = "function"`)
    and httpx binds its connection pool to whichever loop first touches it — a pool left over
    from a previous test would raise "bound to a different event loop".
    """
    yield
    await reset_services()


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer]:
    """Start a PostgreSQL container (once per test session) and apply migrations against it.

    `db/migrations/env.py` builds its connection URL from `DatabaseConfig()`, which reads
    `DB_URL` from the environment — so migrations are pointed at the test container by
    setting that env var directly (rather than via `Config.set_main_option`, which
    `env.py` would immediately overwrite).

    The whole environment is snapshotted and restored around the upgrade, not just `DB_URL`:
    `env.py` also calls `load_dotenv()`, which is right for an operator running
    `alembic upgrade head` by hand but here would push the developer's own `.env` into this
    process for the rest of the session. Every test that constructs a bare `Config()` would
    then be asserting against local values — silently, and depending on test order, since this
    fixture is session-scoped and the suite is randomly ordered.
    """
    with PostgresContainer("postgres:17-alpine") as postgres:
        url = postgres.get_connection_url().replace("+psycopg2", "+asyncpg")
        environment_before_migrations = os.environ.copy()
        os.environ["DB_URL"] = url
        try:
            command.upgrade(Config(str(_SERVICE_ROOT / "alembic.ini")), "head")
        finally:
            os.environ.clear()
            os.environ.update(environment_before_migrations)
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
    config = DatabaseConfig.model_validate({"url": url})
    engine = create_engine(config)
    factory = create_session_factory(engine)
    yield engine, factory
    await engine.dispose()
