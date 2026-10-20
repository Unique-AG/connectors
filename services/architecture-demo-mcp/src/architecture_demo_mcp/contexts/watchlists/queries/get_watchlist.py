from datetime import datetime

from pydantic import BaseModel

from architecture_demo_mcp.contexts.quotes import get_quotes
from architecture_demo_mcp.persistence import list_watchlist
from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.upstream import Upstream


async def get_watchlist(
    *, upstream: Upstream, persistence: Persistence, watchlist: str
) -> list[WatchedAsset]:
    """A ticker IEX does not quote still belongs on the watchlist, without a price."""
    entries = await list_watchlist(persistence=persistence, watchlist=watchlist)
    quotes = await get_quotes(
        upstream=upstream, persistence=persistence, tickers=[entry.ticker for entry in entries]
    )
    return [
        WatchedAsset(
            ticker=entry.ticker,
            note=entry.note,
            added_at=entry.added_at,
            last_price=quote.last_price if quote else None,
            previous_close=quote.previous_close if quote else None,
        )
        for entry in entries
        for quote in [quotes.get(entry.ticker)]
    ]


class WatchedAsset(BaseModel):
    ticker: str
    note: str | None
    added_at: datetime
    last_price: float | None
    previous_close: float | None
