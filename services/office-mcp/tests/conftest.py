from collections.abc import Generator

import pytest
from testcontainers.community.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer]:
    """Start a PostgreSQL container, once per test session.

    The service owns no schema yet — nothing creates tables, so there is nothing to migrate.
    The container exists so the tests that talk to Postgres (readiness, and the DSN checks that
    prove asyncpg actually accepts what `asyncpg_dsn` produces) run against a real server.

    The underlying container is shared across every test in the session and its data persists —
    rows aren't reset between tests or files. Use IDs unique across the whole suite.
    """
    with PostgresContainer("postgres:17-alpine") as postgres:
        yield postgres
