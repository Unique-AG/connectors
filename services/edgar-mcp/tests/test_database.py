import pytest
from sqlalchemy import text
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="module")
def postgres_container():
    """Start a PostgreSQL container for testing."""
    with PostgresContainer("postgres:16-alpine") as postgres:
        yield postgres


@pytest.fixture
async def db(postgres_container):
    """Create engine and session factory, dispose on cleanup."""
    from edgar_mcp.config import DatabaseConfig
    from edgar_mcp.db.engine import create_engine, create_session_factory

    url = postgres_container.get_connection_url().replace("+psycopg2", "")
    config = DatabaseConfig(url=url)
    engine = create_engine(config)
    factory = create_session_factory(engine)
    yield engine, factory
    await engine.dispose()


class TestDatabaseConnection:
    """Test database connection behavior."""

    @pytest.mark.asyncio
    async def test_can_connect_and_query(self, db):
        """Engine can connect to PostgreSQL and execute queries."""
        _, factory = db

        async with factory() as session:
            result = await session.execute(text("SELECT 1 as value"))
            assert result.scalar() == 1

    @pytest.mark.asyncio
    async def test_session_commits_on_success(self, db):
        """Session commits changes when context exits normally."""
        from edgar_mcp.db.engine import get_session

        _, factory = db

        async with factory() as session:
            await session.execute(text("CREATE TABLE IF NOT EXISTS test_commit (id INT)"))
            await session.commit()

        try:
            async with get_session(factory) as session:
                await session.execute(text("INSERT INTO test_commit VALUES (42)"))

            async with factory() as session:
                result = await session.execute(text("SELECT id FROM test_commit"))
                row = result.fetchone()

            assert row[0] == 42
        finally:
            async with factory() as session:
                await session.execute(text("DROP TABLE IF EXISTS test_commit"))
                await session.commit()

    @pytest.mark.asyncio
    async def test_session_rolls_back_on_error(self, db):
        """Session rolls back changes when an exception occurs."""
        from edgar_mcp.db.engine import get_session

        _, factory = db

        async with factory() as session:
            await session.execute(text("CREATE TABLE IF NOT EXISTS test_rollback (id INT)"))
            await session.commit()

        try:
            error_raised = False
            try:
                async with get_session(factory) as session:
                    await session.execute(text("INSERT INTO test_rollback VALUES (99)"))
                    raise ValueError("Simulated error")
            except ValueError:
                error_raised = True

            assert error_raised, "ValueError should have propagated from get_session"

            async with factory() as session:
                result = await session.execute(text("SELECT COUNT(*) FROM test_rollback"))
                count = result.scalar()

            assert count == 0
        finally:
            async with factory() as session:
                await session.execute(text("DROP TABLE IF EXISTS test_rollback"))
                await session.commit()
