import asyncio
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from functools import partial

import httpx2
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from mcp_openapi.upstream import Operation

from tiingo_mcp import server
from tiingo_mcp.settings import Settings
from tiingo_mcp.tools import prices, returns

PRICES = {
    "ABC": [("2026-01-02", 100.0), ("2026-01-05", 110.0)],
    "DEF": [("2026-01-02", 50.0), ("2026-01-05", 45.0)],
}


def tiingo(request: httpx2.Request) -> httpx2.Response:
    ticker = request.url.path.split("/")[-2].upper()
    if ticker not in PRICES:
        return httpx2.Response(404, json={"detail": f"Error: Ticker '{ticker}' not found"})
    rows = [{"date": f"{day}T00:00:00.000Z", "adjClose": price} for day, price in PRICES[ticker]]
    return httpx2.Response(200, json=rows)


@pytest.fixture
def requests_seen(monkeypatch: pytest.MonkeyPatch) -> list[httpx2.Request]:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return tiingo(request)

    monkeypatch.setattr(
        server.httpx2,
        "AsyncClient",
        partial(httpx2.AsyncClient, transport=httpx2.MockTransport(handler)),
    )
    return seen


def with_client[T](settings: Settings, use: Callable[[Client], Awaitable[T]]) -> T:
    async def run() -> T:
        async with Client(server.create_server(settings)) as client:
            return await use(client)

    return asyncio.run(run())


class FakeApi:
    """Answers `call` from canned rows, recording the arguments it got."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def call[T](self, operation: Operation[T], **arguments: str) -> T:
        self.calls.append((operation.operation_id, arguments))
        return operation.adapter.validate_python(self.rows)


def test_recent_daily_prices_asks_for_the_window_since_today() -> None:
    api = FakeApi([{"date": "2026-01-02T00:00:00.000Z", "close": 5.0}])
    bars = asyncio.run(prices.recent_daily_prices("ABC", 30, api=api))
    start = (date.today() - timedelta(days=30)).isoformat()
    assert api.calls == [("getDailyPrices", {"ticker": "ABC", "startDate": start})]
    assert [bar.close for bar in bars] == [5.0]


def test_chart_end_to_end_through_the_server(
    local_settings: Settings, requests_seen: list[httpx2.Request]
) -> None:
    async def call(client: Client):  # noqa: ANN202
        tools = {tool.name: tool for tool in await client.list_tools()}
        result = await client.call_tool(
            "plot_cumulative_returns", {"tickers": ["abc", "ABC", "def"], "lookback_days": 30}
        )
        return tools["plot_cumulative_returns"], result

    tool, result = with_client(local_settings, call)
    assert tool.output_schema["properties"].keys() == {"lookback_days", "start", "end", "series"}
    chart = result.structured_content
    assert [(s["ticker"], s["total_return_pct"]) for s in chart["series"]] == [
        ("ABC", 10.0),
        ("DEF", -10.0),
    ]
    assert (chart["start"], chart["end"]) == ("2026-01-02", "2026-01-05")
    assert "ABC +10.00%, DEF -10.00%" in result.content[0].text
    expected_start = (date.today() - timedelta(days=30)).isoformat()
    assert [r.url.params["startDate"] for r in requests_seen] == [expected_start] * 2


def test_failing_ticker_is_named_in_the_error(
    local_settings: Settings, requests_seen: list[httpx2.Request]
) -> None:
    async def call(client: Client) -> None:
        await client.call_tool("plot_cumulative_returns", {"tickers": ["ABC", "nope"]})

    with pytest.raises(ToolError, match=r"NOPE: 404 Not Found for GET"):
        with_client(local_settings, call)


def test_chart_series_names_a_ticker_without_prices() -> None:
    api = FakeApi([])
    with pytest.raises(ToolError, match="ABC: no price data"):
        asyncio.run(returns.series_for("ABC", 30, api))
