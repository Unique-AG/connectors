from datetime import datetime

from pydantic import BaseModel

from architecture_demo_mcp.contexts.quotes import get_quote
from architecture_demo_mcp.contexts.quotes import Quote
from architecture_demo_mcp.contexts.quotes import QuoteNotFoundError
from architecture_demo_mcp.persistence import list_watchlist
from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.upstream import Upstream


async def get_watchlist(
    *, upstream: Upstream, persistence: Persistence, watchlist: str
) -> list[WatchedAsset]:
    entries = await list_watchlist(persistence=persistence, watchlist=watchlist)
    watched: list[WatchedAsset] = []
    for entry in entries:
        quote = await _quote_or_none(
            upstream=upstream, persistence=persistence, ticker=entry.ticker
        )
        watched.append(
            WatchedAsset(
                ticker=entry.ticker,
                note=entry.note,
                added_at=entry.added_at,
                last_price=quote.last_price if quote else None,
                previous_close=quote.previous_close if quote else None,
            )
        )
    return watched


async def _quote_or_none(
    *, upstream: Upstream, persistence: Persistence, ticker: str
) -> Quote | None:
    """A ticker IEX does not quote still belongs on the watchlist, without a price."""
    try:
        return await get_quote(upstream=upstream, persistence=persistence, ticker=ticker)
    except QuoteNotFoundError:
        return None


class WatchedAsset(BaseModel):
    ticker: str
    note: str | None
    added_at: datetime
    last_price: float | None
    previous_close: float | None
