from collections.abc import Generator

import pytest
from testcontainers.community.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer]:
    """Start a PostgreSQL container, once per test session.

    Nothing is applied to it: this service owns no schema. Its one table (`oauth_kv`) belongs to
    the OAuth state store, which creates it on first use — so the app under test builds it
    itself, the same way it does in production.

    The container is shared across every test in the session and its data persists, so use IDs
    that are unique across the whole suite (a prefix per test file, or a random uuid).
    """
    with PostgresContainer("postgres:17-alpine") as postgres:
        yield postgres
