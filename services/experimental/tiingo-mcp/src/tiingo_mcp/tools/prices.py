from datetime import date, timedelta

from fastmcp import FastMCP
from pydantic import validate_call

from tiingo_mcp.models.vendor_responses import DailyPriceBar
from tiingo_mcp.params import LookbackDays
from tiingo_mcp.tools.wrap import forward_rows, wrap_tool


@validate_call
async def recent_daily_prices(ticker: str, lookback_days: LookbackDays = 30) -> list[DailyPriceBar]:
    """End-of-day OHLCV prices for a ticker over the last `lookback_days`
    calendar days (default 30). Returns open, high, low, close, volume and
    adjusted close per day.
    """
    start = date.today() - timedelta(days=lookback_days)
    rows = await forward_rows(ticker=ticker, startDate=start.isoformat())
    return [DailyPriceBar.model_validate(r) for r in rows]


async def register(mcp: FastMCP) -> None:
    await wrap_tool(mcp, "getDailyPrices", recent_daily_prices)
