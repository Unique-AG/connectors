import asyncio
from collections.abc import Awaitable, Callable
from datetime import date
from functools import partial

import httpx2
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from tiingo_mcp import server
from tiingo_mcp.settings import Settings
from tiingo_mcp.tools import prices, register_tools, returns

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

    transport = httpx2.MockTransport(handler)
    monkeypatch.setattr(
        server.httpx2, "AsyncClient", partial(httpx2.AsyncClient, transport=transport)
    )
    return seen


def with_client[T](settings: Settings, use: Callable[[Client], Awaitable[T]]) -> T:
    async def run() -> T:
        mcp = server.create_server(settings)
        await register_tools(mcp)
        async with Client(mcp) as client:
            return await use(client)

    return asyncio.run(run())


def test_chart_end_to_end_through_the_wrapped_price_tool(
    local_settings: Settings,
    requests_seen: list[httpx2.Request],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Clock:
        @staticmethod
        def today() -> date:
            return date(2026, 2, 1)

    monkeypatch.setattr(prices, "date", Clock)

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
    assert [r.url.params["startDate"] for r in requests_seen] == ["2026-01-02", "2026-01-02"]


def test_failing_ticker_is_named_in_the_error(
    local_settings: Settings, requests_seen: list[httpx2.Request]
) -> None:
    async def call(client: Client) -> None:
        await client.call_tool("plot_cumulative_returns", {"tickers": ["ABC", "nope"]})

    with pytest.raises(ToolError, match=r"NOPE: HTTP error 404"):
        with_client(local_settings, call)


def test_composite_fails_loudly_when_its_dependency_is_not_registered(
    local_settings: Settings,
) -> None:
    async def register() -> None:
        await returns.register(server.create_server(local_settings))

    with pytest.raises(AssertionError, match="recent_daily_prices is not registered"):
        asyncio.run(register())
