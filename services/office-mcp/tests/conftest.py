from collections.abc import Generator

import pytest
from testcontainers.community.postgres import PostgresContainer


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test that pulls in the Postgres container, so `-m "not docker"` can skip them.

    Requesting the fixture is the only signal there is — these tests are spread across files and
    carry no marker of their own. A bare `pytest` still runs everything, as CI does.
    """
    for item in items:
        # Only `Function` items carry fixtures; `Item` does not declare `fixturenames` at all.
        if isinstance(item, pytest.Function) and "postgres_container" in item.fixturenames:
            item.add_marker("docker")


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
