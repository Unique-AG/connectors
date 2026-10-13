import asyncio

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from tiingo_mcp.models.vendor_responses import DailyPriceBar
from tiingo_mcp.server import create_server
from tiingo_mcp.settings import Settings
from tiingo_mcp.tools import register_tools
from tiingo_mcp.tools.returns import WIDGET_URI, cumulative_returns


def bar(day: int, adj_close: float | None) -> DailyPriceBar:
    return DailyPriceBar(date=f"2026-01-{day:02d}T00:00:00.000Z", adjClose=adj_close)


def test_cumulative_returns_sorts_and_rebases_to_first_bar() -> None:
    points = cumulative_returns([bar(3, 110.0), bar(1, 100.0), bar(2, 95.0)])
    assert [(p.date.day, p.return_pct) for p in points] == [(1, 0.0), (2, -5.0), (3, 10.0)]


def test_cumulative_returns_skips_bars_without_a_price() -> None:
    assert [p.date.day for p in cumulative_returns([bar(1, None), bar(2, 50.0), bar(3, 55.0)])] == [
        2,
        3,
    ]
    assert cumulative_returns([bar(1, None)]) == []


def test_cumulative_returns_keeps_a_zero_price() -> None:
    points = cumulative_returns([bar(1, 100.0), bar(2, 0.0), bar(3, 50.0)])
    assert [(p.date.day, p.return_pct) for p in points] == [(1, 0.0), (2, -100.0), (3, -50.0)]


def test_cumulative_returns_rejects_a_zero_starting_price() -> None:
    with pytest.raises(ToolError, match="starts at 0"):
        cumulative_returns([bar(1, 0.0), bar(2, 10.0)])


def test_price_bar_drops_other_vendor_fields() -> None:
    row = {"date": "2026-01-02", "close": 5.0, "divCash": 0.0, "newVendorField": 7}
    assert DailyPriceBar.model_validate(row).model_dump(exclude_none=True) == {
        "date": "2026-01-02",
        "close": 5.0,
    }


def test_returns_app_is_registered_with_its_widget(local_settings: Settings) -> None:
    async def inspect():  # noqa: ANN202
        mcp = create_server(local_settings)
        await register_tools(mcp)
        async with Client(mcp) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            widget = (await client.read_resource(WIDGET_URI))[0]
            return tools, widget

    tools, widget = asyncio.run(inspect())
    assert tools["plot_cumulative_returns"].meta["ui"]["resourceUri"] == WIDGET_URI
    assert "daily_prices" not in tools
    assert "recent_daily_prices" in tools
    assert widget.mime_type == "text/html;profile=mcp-app"
    assert "ui/initialize" in widget.text
