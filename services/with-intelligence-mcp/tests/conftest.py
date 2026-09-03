import logging
import os
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer

from with_intelligence_mcp.teardown import close_singletons

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]

_SERVICE_ROOT = Path(__file__).parent.parent


@pytest.fixture(autouse=True)
def _undo_logger_disabling() -> None:
    """`fileConfig` in the migrations env disables every logger imported before it, killing
    `caplog` in a full-suite run only."""
    for logger in logging.root.manager.loggerDict.values():
        if isinstance(logger, logging.Logger):
            logger.disabled = False


@pytest.fixture(autouse=True)
async def _close_singletons() -> AsyncGenerator[None]:
    """Each test gets its own event loop, and a pool binds to the loop that first touches it."""
    yield
    await close_singletons()


def _migrate(url: str) -> None:
    """Apply migrations against `url`.

    `env.py` reads `DB_URL` from the environment and would overwrite anything set via
    `Config.set_main_option`. It also calls `load_dotenv()`, which would otherwise leak the
    developer's `.env` into every later test in the session — hence the snapshot/restore.
    """
    environment_before = os.environ.copy()
    os.environ["DB_URL"] = url
    try:
        command.upgrade(Config(str(_SERVICE_ROOT / "alembic.ini")), "head")
    finally:
        os.environ.clear()
        os.environ.update(environment_before)


@pytest.fixture(scope="session")
def database_url() -> Generator[str]:
    """A migrated Postgres for the session.

    `TEST_DB_URL` points the suite at a Postgres that is already running, which is what a
    machine without Docker needs; otherwise a container is started, which is what CI does.
    """
    provided = os.environ.get("TEST_DB_URL")
    if provided:
        url = provided.replace("postgresql://", "postgresql+asyncpg://")
        _migrate(url)
        yield url
        return

    with PostgresContainer("postgres:17-alpine") as postgres:
        url = postgres.get_connection_url().replace("+psycopg2", "+asyncpg")
        _migrate(url)
        yield url


@pytest.fixture
async def db(database_url: str) -> AsyncGenerator[DatabaseFixture]:
    """The database is shared across the session and rows persist — use suite-unique ids."""
    from with_intelligence_mcp.config import DatabaseConfig
    from with_intelligence_mcp.db import create_engine, create_session_factory

    config = DatabaseConfig.model_validate({"url": database_url})
    engine = create_engine(config)
    factory = create_session_factory(engine)
    yield engine, factory
    await engine.dispose()
