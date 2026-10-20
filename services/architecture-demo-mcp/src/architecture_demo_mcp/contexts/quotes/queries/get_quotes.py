from architecture_demo_mcp.contexts.quotes.models import Quote
from architecture_demo_mcp.persistence import cache_quotes
from architecture_demo_mcp.persistence import cached_quotes
from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.upstream import GET_IEX_TOP_OF_BOOK
from architecture_demo_mcp.upstream import Upstream


async def get_quotes(
    *, upstream: Upstream, persistence: Persistence, tickers: list[str]
) -> dict[str, Quote]:
    """The quote of each ticker IEX quotes, in one request for every ticker not in the cache.

    Filling the cache changes nothing a caller can see, so this is still a query.
    """
    cached = await cached_quotes(persistence=persistence, tickers=tickers, model=Quote)
    missing = [ticker for ticker in tickers if ticker not in cached]
    if not missing:
        return cached
    books = await upstream.call(GET_IEX_TOP_OF_BOOK, tickers=",".join(missing))
    fetched = {
        book.ticker.upper(): Quote(
            ticker=book.ticker.upper(),
            last_price=book.tngoLast,
            previous_close=book.prevClose,
            as_of=book.timestamp,
        )
        for book in books
        if book.ticker is not None and book.ticker.upper() in missing
    }
    await cache_quotes(persistence=persistence, quotes=fetched)
    return {**cached, **fetched}
