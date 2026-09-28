from collections.abc import AsyncIterator, Generator

import httpx
import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.transports import FastMCPTransport
from kiota_http.middleware import retry_handler
from testcontainers.community.postgres import PostgresContainer

from office_365_mcp.tools import TOOL_NAMES, register_tools, resolve


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
    """No schema is applied: this service owns none, and the OAuth state store creates its one
    table (`oauth_kv`) on first use. Data persists across the whole session, so use ids unique to
    the suite — a prefix per test file, or a random uuid."""
    with PostgresContainer("postgres:17-alpine") as postgres:
        yield postgres


class RecordedSleeps:
    """Stands in for the `asyncio` module inside the SDK's retry handler, which only calls
    `await asyncio.sleep(delay)`. Patching `asyncio.sleep` globally would slow everything else on
    the loop."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)


@pytest.fixture
def retry_sleeps(monkeypatch: pytest.MonkeyPatch) -> RecordedSleeps:
    recorded = RecordedSleeps()
    monkeypatch.setattr(retry_handler, "asyncio", recorded)
    return recorded


@pytest.fixture
async def every_tool() -> AsyncIterator[Client[FastMCPTransport]]:
    server = FastMCP[None](name="every-tool")
    transport = httpx.AsyncClient()
    register_tools(server, transport, resolve(preset=None, enabled=list(TOOL_NAMES)))
    async with Client(FastMCPTransport(server)) as client:
        yield client
    await transport.aclose()
