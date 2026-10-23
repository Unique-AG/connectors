from datetime import date

from architecture_demo_mcp.contexts.prices.models import DailyClose
from architecture_demo_mcp.persistence import cache_price_history
from architecture_demo_mcp.persistence import cached_price_history
from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.upstream import DailyPriceBar
from architecture_demo_mcp.upstream import GET_DAILY_PRICES
from architecture_demo_mcp.upstream import Upstream


async def get_daily_closes(
    *,
    upstream: Upstream,
    persistence: Persistence,
    ticker: str,
    start_date: date | None,
    end_date: date | None,
) -> list[DailyClose]:
    """The ticker's adjusted daily closes, oldest first, from the cache when it has them.

    Without a start date Tiingo sends the latest trading day alone. Filling the cache changes
    nothing a caller can see, so this still only reads.
    """
    key = f"{ticker}:{start_date or 'latest'}:{end_date or 'latest'}"
    cached = await cached_price_history(persistence=persistence, key=key, model=DailyClose)
    if cached is not None:
        return cached
    bars = await upstream.call(
        GET_DAILY_PRICES,
        ticker=ticker,
        startDate=start_date.isoformat() if start_date else None,
        endDate=end_date.isoformat() if end_date else None,
    )
    closes = [close for bar in bars if (close := _daily_close(bar=bar)) is not None]
    await cache_price_history(persistence=persistence, key=key, bars=closes)
    return closes


def _daily_close(*, bar: DailyPriceBar) -> DailyClose | None:
    """None for a bar Tiingo sent half-filled or without a positive close, which no figure can
    use, since every return and weight divides by a close.
    """
    if bar.date is None or bar.adj_close is None or bar.adj_close <= 0:
        return None
    # Tiingo sends a date as midnight UTC, such as 2026-10-19T00:00:00.000Z.
    return DailyClose(
        date=date.fromisoformat(bar.date[:10]),
        close=bar.adj_close,
        high=bar.adj_high,
        low=bar.adj_low,
    )
