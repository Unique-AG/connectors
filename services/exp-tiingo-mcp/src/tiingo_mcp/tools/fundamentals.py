from typing import Annotated, Literal, get_args

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from pydantic import Field, TypeAdapter

from tiingo_mcp.deps import get_api
from tiingo_mcp.helpers.openapi import TOOL_HINTS
from tiingo_mcp.helpers.upstream import Operation, OperationClient
from tiingo_mcp.models.fundamentals import FinancialPeriod
from tiingo_mcp.models.vendor_responses import FundamentalsDaily, FundamentalsStatement
from tiingo_mcp.params import LookbackDays, since

Section = Literal["overview", "incomeStatement", "balanceSheet", "cashFlow"]
Periods = Annotated[int, Field(ge=1, le=20)]
FundamentalsTicker = Annotated[
    str,
    Field(
        min_length=1,
        description="Use the ticker for active symbols, or Tiingo PermaTicker (stable identifier) "
        "for delisted/recycled symbols.",
    ),
]
GET_STATEMENTS = Operation("getFundamentalsStatements", TypeAdapter(list[FundamentalsStatement]))
GET_DAILY_FUNDAMENTALS = Operation("getFundamentalsDaily", TypeAdapter(list[FundamentalsDaily]))


def recent_financial_periods(
    statements: list[FundamentalsStatement], periods: int, sections: list[Section] | None
) -> list[FinancialPeriod]:
    """The newest `periods` quarterly statements, limited to `sections` (default all)."""
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


@tool(annotations=TOOL_HINTS)
async def recent_financials(
    ticker: FundamentalsTicker,
    periods: Periods = 4,
    sections: list[Section] | None = None,
    api: OperationClient = Depends(get_api),
) -> list[FinancialPeriod]:
    """Latest reported financials for a ticker, newest first. `periods` is how many
    quarterly periods to return (default 4); annual (quarter 0) rows are skipped.
    `sections` limits the output to overview, incomeStatement, balanceSheet and/or
    cashFlow (default all). Each section maps Tiingo data codes to values; the codes
    are explained in the resource://fundamentals_definitions resource.
    """
    statements = await api.call(GET_STATEMENTS, ticker=ticker)
    return recent_financial_periods(statements, periods, sections)


@tool(annotations=TOOL_HINTS)
async def recent_valuation_metrics(
    ticker: FundamentalsTicker,
    lookback_days: LookbackDays = 30,
    api: OperationClient = Depends(get_api),
) -> list[FundamentalsDaily]:
    """Daily market cap, enterprise value, P/E, P/B and trailing PEG for a ticker
    over the last `lookback_days` calendar days (default 30).
    """
    return await api.call(GET_DAILY_FUNDAMENTALS, ticker=ticker, startDate=since(lookback_days))
