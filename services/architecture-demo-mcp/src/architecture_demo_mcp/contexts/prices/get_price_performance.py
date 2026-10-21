from datetime import date
from itertools import accumulate
from itertools import pairwise
from math import sqrt
from statistics import stdev

from pydantic import BaseModel
from pydantic import Field

from architecture_demo_mcp.contexts.prices.get_daily_closes import get_daily_closes
from architecture_demo_mcp.contexts.prices.models import DailyClose
from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.upstream import Upstream


async def get_price_performance(
    *,
    upstream: Upstream,
    persistence: Persistence,
    ticker: str,
    start_date: date,
    end_date: date | None,
) -> PricePerformance:
    if end_date is not None and end_date < start_date:
        raise PerformanceUnavailableError(f"The period ends on {end_date}, before {start_date}.")
    closes = await get_daily_closes(
        upstream=upstream,
        persistence=persistence,
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
    )
    if len(closes) < _MIN_TRADING_DAYS:
        raise PerformanceUnavailableError(
            f"Tiingo has {len(closes)} trading day(s) of {ticker} in the period, and a "
            f"performance needs at least {_MIN_TRADING_DAYS}."
        )
    first, last = closes[0], closes[-1]
    daily_returns = [later.close / earlier.close - 1 for earlier, later in pairwise(closes)]
    return PricePerformance(
        ticker=ticker,
        first_date=first.date,
        last_date=last.date,
        trading_days=len(closes),
        first_close=first.close,
        last_close=last.close,
        total_return=round(last.close / first.close - 1, 6),
        annualized_volatility=_annualized_volatility(daily_returns=daily_returns),
        max_drawdown=_max_drawdown(closes=closes),
        period_high=max(close.high or close.close for close in closes),
        period_low=min(close.low or close.close for close in closes),
    )


def _annualized_volatility(*, daily_returns: list[float]) -> float | None:
    """None for a single return, which has no spread."""
    if len(daily_returns) < 2:
        return None
    return round(stdev(daily_returns) * sqrt(_TRADING_DAYS_PER_YEAR), 6)


def _max_drawdown(*, closes: list[DailyClose]) -> float:
    peaks = accumulate((close.close for close in closes), max)
    return round(max(1 - close.close / peak for close, peak in zip(closes, peaks, strict=True)), 6)


class PricePerformance(BaseModel):
    ticker: str
    first_date: date
    last_date: date
    trading_days: int
    first_close: float
    last_close: float
    total_return: float = Field(description="0.12 is a 12% gain from the first to the last close.")
    annualized_volatility: float | None = Field(
        description="The standard deviation of daily returns, scaled to 252 trading days."
    )
    max_drawdown: float = Field(
        description="The largest fall from a running high close, 0.25 for 25%."
    )
    period_high: float
    period_low: float


class PerformanceUnavailableError(Exception):
    """The period has too few trading days, or ends before it starts."""


_MIN_TRADING_DAYS = 2
_TRADING_DAYS_PER_YEAR = 252
