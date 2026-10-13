from datetime import date, timedelta
from typing import Annotated, Literal, get_args

from fastmcp import FastMCP
from pydantic import Field, validate_call

from tiingo_mcp.models.fundamentals import FinancialPeriod
from tiingo_mcp.models.vendor_responses import FundamentalsDaily, FundamentalsStatement
from tiingo_mcp.params import LookbackDays
from tiingo_mcp.tools.wrap import forward_rows, wrap_tool

Section = Literal["overview", "incomeStatement", "balanceSheet", "cashFlow"]
Periods = Annotated[int, Field(ge=1, le=20)]


@validate_call
async def recent_financials(
    ticker: str, periods: Periods = 4, sections: list[Section] | None = None
) -> list[FinancialPeriod]:
    """Latest reported financials for a ticker, newest first. `periods` is how many
    quarterly periods to return (default 4); annual (quarter 0) rows are skipped.
    `sections` limits the output to overview, incomeStatement, balanceSheet and/or
    cashFlow (default all). Each section maps Tiingo data codes to values; the codes
    are explained in the resource://fundamentals_definitions resource.
    """
    payload = await forward_rows(ticker=ticker)
    statements = (FundamentalsStatement.model_validate(r) for r in payload)
    rows = sorted(
        (row for row in statements if row.quarter != 0),
        key=lambda row: row.date or "",
        reverse=True,
    )
    wanted = list(get_args(Section)) if sections is None else sections
    return [
        FinancialPeriod(
            date=row.date,
            year=row.year,
            quarter=row.quarter,
            statements={
                section: {
                    item.dataCode: item.value
                    for item in getattr(row.statementData, section, None) or []
                    if item.dataCode
                }
                for section in wanted
            },
        )
        for row in rows[:periods]
    ]


@validate_call
async def recent_valuation_metrics(
    ticker: str, lookback_days: LookbackDays = 30
) -> list[FundamentalsDaily]:
    """Daily market cap, enterprise value, P/E, P/B and trailing PEG for a ticker
    over the last `lookback_days` calendar days (default 30).
    """
    start = date.today() - timedelta(days=lookback_days)
    rows = await forward_rows(ticker=ticker, startDate=start.isoformat())
    return [FundamentalsDaily.model_validate(r) for r in rows]


async def register(mcp: FastMCP) -> None:
    await wrap_tool(mcp, "getFundamentalsStatements", recent_financials)
    await wrap_tool(mcp, "getFundamentalsDaily", recent_valuation_metrics)
