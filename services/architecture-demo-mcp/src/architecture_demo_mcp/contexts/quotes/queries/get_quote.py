from architecture_demo_mcp.contexts.quotes.models import Quote
from architecture_demo_mcp.contexts.quotes.queries.get_quotes import get_quotes
from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.upstream import Upstream


async def get_quote(*, upstream: Upstream, persistence: Persistence, ticker: str) -> Quote:
    quotes = await get_quotes(upstream=upstream, persistence=persistence, tickers=[ticker])
    if ticker not in quotes:
        raise QuoteNotFoundError(f"IEX has no quote for {ticker}.")
    return quotes[ticker]


class QuoteNotFoundError(Exception):
    """IEX does not quote the ticker, as for a mutual fund or a delisted stock."""
