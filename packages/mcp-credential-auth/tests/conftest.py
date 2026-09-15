from collections.abc import AsyncGenerator, Generator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from mcp_credential_auth import AuthBase


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer]:
    with PostgresContainer("postgres:17-alpine") as postgres:
        yield postgres


@pytest.fixture
async def session_factory(
    postgres_container: PostgresContainer,
) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    url = postgres_container.get_connection_url().replace("+psycopg2", "+asyncpg")
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(AuthBase.metadata.create_all)

    yield async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(AuthBase.metadata.drop_all)
    await engine.dispose()
