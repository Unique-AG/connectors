import asyncio
from pathlib import Path
from typing import Annotated

import httpx2
from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolResult
from pydantic import Field

from tiingo_mcp.models.returns import ReturnPoint, ReturnsChart, ReturnSeries
from tiingo_mcp.models.vendor_responses import DailyPriceBar
from tiingo_mcp.params import LookbackDays
from tiingo_mcp.tools.wrap import require_tool, run_rows

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
        raise ToolError("adjusted close starts at 0")
    return [
        ReturnPoint(date=day, return_pct=round((adj_close / base - 1) * 100, 2))
        for day, adj_close in priced
    ]


async def register(mcp: FastMCP) -> None:
    prices = await require_tool(mcp, "recent_daily_prices")  # need to register `prices` before.

    async def series_for(ticker: str, lookback_days: int) -> ReturnSeries:
        try:
            bars = await run_rows(
                prices, {"ticker": ticker, "lookback_days": lookback_days}, DailyPriceBar
            )
        except httpx2.HTTPError as exc:
            raise ToolError(f"{ticker}: {exc}") from exc
        try:
            points = cumulative_returns(bars)
        except ToolError as exc:
            raise ToolError(f"{ticker}: {exc}") from exc
        if not points:
            raise ToolError(f"{ticker}: no price data in this period")
        return ReturnSeries(ticker=ticker, total_return_pct=points[-1].return_pct, points=points)

    @mcp.tool(
        name="plot_cumulative_returns",
        output_schema=ReturnsChart.model_json_schema(),
        annotations={"readOnlyHint": True, "openWorldHint": True},
        app=AppConfig(resource_uri=WIDGET_URI),
    )
    async def plot_cumulative_returns(
        tickers: Tickers, lookback_days: LookbackDays = 90
    ) -> ToolResult:
        """Line chart of cumulative return (adjusted close, % since the start) for 1 to 5 tickers.

        Covers the last `lookback_days` calendar days (default 90). Use it to compare performance.
        The chart is shown in the app; still state the key figures in your answer.
        """
        symbols = list(dict.fromkeys(ticker.upper() for ticker in tickers))
        series = await asyncio.gather(*(series_for(symbol, lookback_days) for symbol in symbols))
        dates = [point.date for s in series for point in s.points]
        chart = ReturnsChart(
            lookback_days=lookback_days, start=min(dates), end=max(dates), series=series
        )
        summary = ", ".join(f"{s.ticker} {s.total_return_pct:+.2f}%" for s in series)
        text = f"Cumulative return {chart.start} to {chart.end} (adjusted close): {summary}."
        return ToolResult(content=text, structured_content=chart.model_dump(mode="json"))

    @mcp.resource(WIDGET_URI, name="Cumulative returns chart", app=AppConfig(prefers_border=True))
    def widget() -> str:
        return WIDGET_PATH.read_text()
