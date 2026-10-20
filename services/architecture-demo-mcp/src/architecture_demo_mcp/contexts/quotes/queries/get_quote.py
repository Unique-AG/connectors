from pydantic import BaseModel

from architecture_demo_mcp.persistence import cache_quote
from architecture_demo_mcp.persistence import cached_quote
from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.upstream import GET_IEX_TOP_OF_BOOK
from architecture_demo_mcp.upstream import Upstream


async def get_quote(*, upstream: Upstream, persistence: Persistence, ticker: str) -> Quote:
    """Filling the cache changes nothing a caller can see, so this is still a query."""
    cached = await cached_quote(persistence=persistence, ticker=ticker, model=Quote)
    if cached is not None:
        return cached
    books = await upstream.call(GET_IEX_TOP_OF_BOOK, tickers=ticker)
    if not books:
        raise QuoteNotFoundError(f"IEX has no quote for {ticker}.")
    book = books[0]
    quote = Quote(
        ticker=book.ticker or ticker,
        last_price=book.tngoLast,
        previous_close=book.prevClose,
        as_of=book.timestamp,
    )
    await cache_quote(persistence=persistence, ticker=ticker, quote=quote)
    return quote


class Quote(BaseModel):
    ticker: str
    last_price: float | None
    previous_close: float | None
    as_of: str | None


class QuoteNotFoundError(Exception):
    """IEX does not quote the ticker, as for a mutual fund or a delisted stock."""
