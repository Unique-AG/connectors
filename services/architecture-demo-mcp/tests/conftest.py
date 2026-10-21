# mcp-scaffold-version: 0.0.1, timestamp: 2026-10-21T12:09:32+00:00

from collections.abc import AsyncGenerator, Awaitable, Callable

from fastmcp import Client
from fastmcp import FastMCP
from fastmcp.client.client import CallToolResult
import httpx2
from mcp_configs import ServerSettings
import pytest

from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.upstream import UpstreamSettings
from tests.offline_server import build_server
from tests.offline_server import fake_upstream_settings
from tests.offline_server import open_fake_persistence

type CallTool = Callable[[str, dict[str, object]], Awaitable[CallToolResult]]

ACME_META = {
    "ticker": "acme",
    "name": "Acme Corporation",
    "description": "Makes anvils and rockets.",
    "exchangeCode": "NASDAQ",
    "startDate": "1990-01-02",
    "endDate": "2026-10-20",
}
GLOBEX_META = {**ACME_META, "ticker": "globex", "name": "Globex Corporation"}
# A fund Tiingo lists but has never priced.
UNPRICED_META = {**ACME_META, "ticker": "unprx", "startDate": None, "endDate": None}


def daily_bar(day: str, adj_close: float) -> dict[str, object]:
    return {
        "date": f"{day}T00:00:00.000Z",
        "close": adj_close * 2,
        "adjClose": adj_close,
        "adjHigh": adj_close + 1,
        "adjLow": adj_close - 1,
        "volume": 1000,
    }


ACME_OCTOBER = [
    daily_bar("2026-10-14", 100),
    daily_bar("2026-10-15", 110),
    daily_bar("2026-10-16", 99),
    daily_bar("2026-10-19", 121),
]
LATEST_CLOSES = {"ACME": daily_bar("2026-10-20", 120), "GLOBEX": daily_bar("2026-10-20", 40)}


class FakeTiingo:
    """Tiingo, answering from fixed data and keeping every request it got."""

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []

    async def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        match request.url.path.split("/")[1:]:
            case ["tiingo", "utilities", "search"]:
                return httpx2.Response(200, json=[{"ticker": "ACME", "name": "Acme Corporation"}])
            case ["tiingo", "daily", "ACME"]:
                return httpx2.Response(200, json=ACME_META)
            case ["tiingo", "daily", "GLOBEX"]:
                return httpx2.Response(200, json=GLOBEX_META)
            case ["tiingo", "daily", "UNPRX"]:
                return httpx2.Response(200, json=UNPRICED_META)
            case ["tiingo", "daily", "ACME", "prices"] if "startDate" in request.url.params:
                return httpx2.Response(200, json=self._october(request))
            case ["tiingo", "daily", ticker, "prices"] if ticker in LATEST_CLOSES:
                return httpx2.Response(200, json=[LATEST_CLOSES[ticker]])
            case _:
                return httpx2.Response(404, json={"detail": "Not found."})

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]

    @staticmethod
    def _october(request: httpx2.Request) -> list[dict[str, object]]:
        params = dict(request.url.params.items())
        start, end = params["startDate"], params.get("endDate", "9999-12-31")
        return [bar for bar in ACME_OCTOBER if start <= str(bar["date"])[:10] <= end]


@pytest.fixture
def server_settings() -> ServerSettings:
    return ServerSettings(_env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.fixture
def upstream_settings() -> UpstreamSettings:
    return fake_upstream_settings()


@pytest.fixture
def tiingo() -> FakeTiingo:
    return FakeTiingo()


@pytest.fixture
def upstream_transport(tiingo: FakeTiingo) -> httpx2.MockTransport:
    return httpx2.MockTransport(tiingo)


@pytest.fixture
async def persistence() -> AsyncGenerator[Persistence]:
    async with open_fake_persistence() as fake:
        yield fake


@pytest.fixture
def server(
    upstream_settings: UpstreamSettings,
    persistence: Persistence,
    upstream_transport: httpx2.MockTransport,
) -> FastMCP:
    return build_server(upstream_settings, persistence, upstream_transport)


@pytest.fixture
def call_tool(server: FastMCP) -> CallTool:
    """Calls a tool through a real FastMCP client, as the platform does."""

    async def call(name: str, arguments: dict[str, object]) -> CallToolResult:
        async with Client(server) as client:
            return await client.call_tool(name, arguments, raise_on_error=False)

    return call
