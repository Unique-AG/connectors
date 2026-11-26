from datetime import date
from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp_observability import trace_arguments
from mcp_types import ToolAnnotations
from pydantic import Field

from architecture_demo_mcp import contexts
from architecture_demo_mcp.mcp.dependencies import get_upstream
from architecture_demo_mcp.mcp.inputs.ticker import Ticker
from architecture_demo_mcp.upstream import Upstream


@tool(
    title="Get Daily Prices",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
@trace_arguments("ticker", "start_date", "end_date", "resample_freq")
async def get_daily_prices(
    *,
    ticker: Ticker,
    start_date: Annotated[
        date | None,
        Field(
            description="The first day, `YYYY-MM-DD`. Leave both dates out for the latest "
            "trading day alone."
        ),
    ] = None,
    end_date: Annotated[
        date | None,
        Field(description="The last day, `YYYY-MM-DD`. Leave it out for today."),
    ] = None,
    resample_freq: Annotated[
        contexts.ResampleFrequency | None,
        Field(
            description="Period per row: `daily` (the default, with holidays), `weekly`, "
            "`monthly` or `annually`. A longer period widens the dates to whole periods."
        ),
    ] = None,
    upstream: Upstream = Depends(get_upstream),
) -> contexts.DailyPrices:
    """Get a ticker's open, high, low, close and volume per period, raw and adjusted for splits
    and dividends, oldest first. The result's `title` names the ticker and the dates covered:
    cite the prices by it.

    For a summary of how the price moved, call `get_price_performance`.
    """
    return await contexts.get_daily_prices(
        upstream=upstream,
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        resample_freq=resample_freq,
    )
