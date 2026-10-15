import asyncio
from pathlib import Path
from typing import Annotated

from fastmcp.apps import AppConfig, app_config_to_meta_dict
from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.resources import resource
from fastmcp.tools import ToolResult, tool
from pydantic import Field

from tiingo_mcp.deps import get_api
from tiingo_mcp.helpers.openapi import TOOL_HINTS
from tiingo_mcp.helpers.upstream import OperationClient, UpstreamError
from tiingo_mcp.models.returns import ReturnPoint, ReturnsChart, ReturnSeries
from tiingo_mcp.models.vendor_responses import DailyPriceBar
from tiingo_mcp.params import LookbackDays
from tiingo_mcp.tools import prices

WIDGET_URI = "ui://tiingo/returns.html"
WIDGET_PATH = Path(__file__).parents[1] / "apps" / "returns.html"
Tickers = Annotated[list[str], Field(min_length=1, max_length=5)]


def cumulative_returns(bars: list[DailyPriceBar]) -> list[ReturnPoint]:
    """Adjusted-close return since the first priced bar, in percent."""
    priced = sorted(
        (bar.date, bar.adjClose)
        for bar in bars
        if bar.date is not None and bar.adjClose is not None
    )
    if not priced:
        return []
    base = priced[0][1]
    if base == 0:
        raise ValueError("adjusted close starts at 0")
    return [
        ReturnPoint(date=day, return_pct=round((adj_close / base - 1) * 100, 2))
        for day, adj_close in priced
    ]


async def series_for(ticker: str, lookback_days: int, api: OperationClient) -> ReturnSeries:
    try:
        # A direct call skips Depends. Alternative: api.call(prices.GET_DAILY_PRICES, ...).
        bars = await prices.recent_daily_prices(ticker=ticker, lookback_days=lookback_days, api=api)
        points = cumulative_returns(bars)
    except (UpstreamError, ValueError) as exc:
        raise ToolError(f"{ticker}: {exc}") from exc
    if not points:
        raise ToolError(f"{ticker}: no price data in this period")
    return ReturnSeries(ticker=ticker, total_return_pct=points[-1].return_pct, points=points)


@tool(
    output_schema=ReturnsChart.model_json_schema(),
    annotations=TOOL_HINTS,
    meta={"ui": app_config_to_meta_dict(AppConfig(resource_uri=WIDGET_URI))},
)
async def plot_cumulative_returns(
    tickers: Tickers,
    lookback_days: LookbackDays = 90,
    api: OperationClient = Depends(get_api),
) -> ToolResult:
    """Line chart of cumulative return (adjusted close, % since the start) for 1 to 5 tickers.

    Covers the last `lookback_days` calendar days (default 90). Use it to compare performance.
    The chart is shown in the app; still state the key figures in your answer.
    """
    symbols = list(dict.fromkeys(ticker.upper() for ticker in tickers))
    series = await asyncio.gather(*(series_for(symbol, lookback_days, api) for symbol in symbols))
    dates = [point.date for s in series for point in s.points]
    chart = ReturnsChart(
        lookback_days=lookback_days, start=min(dates), end=max(dates), series=series
    )
    summary = ", ".join(f"{s.ticker} {s.total_return_pct:+.2f}%" for s in series)
    text = f"Cumulative return {chart.start} to {chart.end} (adjusted close): {summary}."
    return ToolResult(content=text, structured_content=chart.model_dump(mode="json"))


@resource(
    WIDGET_URI,
    name="Cumulative returns chart",
    mime_type="text/html;profile=mcp-app",
    meta={"ui": app_config_to_meta_dict(AppConfig(prefers_border=True))},
)
def widget() -> str:
    return WIDGET_PATH.read_text()
