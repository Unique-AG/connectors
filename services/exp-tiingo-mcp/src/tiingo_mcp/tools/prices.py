from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from pydantic import TypeAdapter

from tiingo_mcp.deps import get_api
from tiingo_mcp.helpers.openapi import TOOL_HINTS
from tiingo_mcp.helpers.upstream import Operation, OperationClient
from tiingo_mcp.models.vendor_responses import DailyPriceBar
from tiingo_mcp.params import LookbackDays, Ticker, since

GET_DAILY_PRICES = Operation("getDailyPrices", TypeAdapter(list[DailyPriceBar]))


@tool(annotations=TOOL_HINTS)
async def recent_daily_prices(
    ticker: Ticker,
    lookback_days: LookbackDays = 30,
    api: OperationClient = Depends(get_api),
) -> list[DailyPriceBar]:
    """End-of-day OHLCV prices for a ticker over the last `lookback_days`
    calendar days (default 30). Returns open, high, low, close, volume and
    adjusted close per day.
    """
    return await api.call(GET_DAILY_PRICES, ticker=ticker, startDate=since(lookback_days))
