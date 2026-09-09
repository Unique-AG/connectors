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
    """Re-enable loggers disabled by Alembic configuration."""
    for logger in logging.root.manager.loggerDict.values():
        if isinstance(logger, logging.Logger):
            logger.disabled = False


@pytest.fixture(autouse=True)
async def _close_singletons() -> AsyncGenerator[None]:
    """Drop cached providers between tests."""
    yield
    await close_singletons()


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer]:
    """Run migrated PostgreSQL for the test session."""
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
    """Yield a database engine and session factory."""
    from with_intelligence_mcp.config import DatabaseConfig
    from with_intelligence_mcp.db import create_engine, create_session_factory

    url = postgres_container.get_connection_url().replace("+psycopg2", "")
    config = DatabaseConfig.model_validate({"url": url})
    engine = create_engine(config)
    factory = create_session_factory(engine)
    yield engine, factory
    await engine.dispose()
