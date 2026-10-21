from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastmcp import Client
from fastmcp import FastMCP
from fastmcp.client.client import CallToolResult
import httpx2
from key_value.aio.stores.memory import MemoryStore
from mcp_configs import ServerSettings
from pydantic import SecretStr
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from architecture_demo_mcp.mcp import create_server
from architecture_demo_mcp.persistence import Base
from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.upstream import UpstreamSettings

type CallTool = Callable[[str, dict[str, object]], Awaitable[CallToolResult]]

ACME_META = {
    "ticker": "ACME",
    "name": "Acme Corporation",
    "description": "Makes anvils and rockets.",
    "exchangeCode": "NASDAQ",
    "startDate": "1990-01-02",
    "endDate": "2026-10-19",
}
ACME_TOP_OF_BOOK = {
    "ticker": "ACME",
    "tngoLast": 101.25,
    "prevClose": 99.5,
    "timestamp": "2026-10-20T14:30:00+00:00",
}
ACME_DAILY_PRICES = [
    {
        "date": "2026-10-19T00:00:00.000Z",
        "open": 99.0,
        "high": 100.0,
        "low": 98.5,
        "close": 99.5,
        "volume": 1200,
    }
]
FUND_META = {**ACME_META, "ticker": "ACMFX", "name": "Acme Growth Fund"}


class FakeTiingo:
    """The example upstream, answering from fixed data and keeping every request it got."""

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []

    async def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        match request.method, request.url.path, request.url.query:
            case "GET", "/tiingo/utilities/search", bytes():
                return httpx2.Response(
                    200,
                    json=[
                        {
                            "ticker": "ACME",
                            "name": "Acme Corporation",
                            "assetType": "Stock",
                            "isActive": True,
                        },
                        {"ticker": None, "name": "A result without a ticker"},
                    ],
                )
            case "GET", "/tiingo/daily/ACME", bytes():
                return httpx2.Response(200, json=ACME_META)
            case "GET", "/tiingo/daily/ACMFX", bytes():
                return httpx2.Response(200, json=FUND_META)
            case "GET", "/tiingo/daily/ACME/prices", bytes():
                return httpx2.Response(200, json=ACME_DAILY_PRICES)
            case "GET", "/iex", bytes():
                tickers = request.url.params["tickers"].split(",")
                return httpx2.Response(200, json=[ACME_TOP_OF_BOOK] if "ACME" in tickers else [])
            case _:
                return httpx2.Response(404, json={"detail": "Not found."})

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]


@pytest.fixture
def server_settings() -> ServerSettings:
    return ServerSettings(_env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.fixture
def upstream_settings() -> UpstreamSettings:
    return UpstreamSettings(api_key=SecretStr("dummy-api-key"), _env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.fixture
def tiingo() -> FakeTiingo:
    return FakeTiingo()


@pytest.fixture
def upstream_transport(tiingo: FakeTiingo) -> httpx2.MockTransport:
    return httpx2.MockTransport(tiingo)


@pytest.fixture
async def persistence() -> AsyncGenerator[Persistence]:
    """SQLite and an in-memory store in place of Postgres and Redis, shared by every client.

    StaticPool hands every session the one connection, so writes never run side by side here. A
    test of two writes racing needs a real Postgres.
    """
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield Persistence(
        database=async_sessionmaker(engine, expire_on_commit=False), store=MemoryStore()
    )
    await engine.dispose()


@pytest.fixture
def server(
    upstream_settings: UpstreamSettings,
    persistence: Persistence,
    upstream_transport: httpx2.MockTransport,
) -> FastMCP:
    @asynccontextmanager
    async def open_persistence() -> AsyncGenerator[Persistence]:
        yield persistence

    return create_server(upstream_settings, open_persistence, upstream_transport)


@pytest.fixture
def call_tool(server: FastMCP) -> CallTool:
    """Calls a tool through a real FastMCP client, as the platform does."""

    async def call(name: str, arguments: dict[str, object]) -> CallToolResult:
        async with Client(server) as client:
            return await client.call_tool(name, arguments, raise_on_error=False)

    return call
