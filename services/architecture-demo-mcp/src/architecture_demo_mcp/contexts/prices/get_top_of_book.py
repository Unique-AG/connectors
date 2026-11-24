from architecture_demo_mcp.contexts.prices.models import Quote
from architecture_demo_mcp.contexts.prices.models import TopOfBook
from architecture_demo_mcp.upstream import GET_IEX_TOP_OF_BOOK
from architecture_demo_mcp.upstream import GetIexTopOfBookQuery
from architecture_demo_mcp.upstream import GetIexTopOfBookRequest
from architecture_demo_mcp.upstream import IexTopOfBook
from architecture_demo_mcp.upstream import Upstream

_TITLED_TICKERS = 5


async def get_top_of_book(*, upstream: Upstream, tickers: list[str]) -> TopOfBook:
    """The latest IEX quote of each ticker, or of every ticker IEX quotes when none is given,
    titled by the tickers so a chat can cite them.
    """
    books = await upstream.call(
        GET_IEX_TOP_OF_BOOK,
        GetIexTopOfBookRequest(
            query=GetIexTopOfBookQuery(tickers=",".join(tickers) if tickers else None)
        ),
    )
    quotes = [quote for book in books if (quote := _quote(book=book)) is not None]
    return TopOfBook(title=_title(quotes=quotes), quotes=quotes)


def _quote(*, book: IexTopOfBook) -> Quote | None:
    """None for a quote Tiingo sent without a ticker, which no one could tell apart."""
    if book.ticker is None:
        return None
    return Quote(
        ticker=book.ticker.upper(),
        timestamp=book.timestamp,
        last=book.last,
        tngo_last=book.tngo_last,
        prev_close=book.prev_close,
        open=book.open,
        high=book.high,
        low=book.low,
        mid=book.mid,
        bid_price=book.bid_price,
        bid_size=book.bid_size,
        ask_price=book.ask_price,
        ask_size=book.ask_size,
        volume=book.volume,
    )


def _title(*, quotes: list[Quote]) -> str:
    """Such as `IEX top of book: AAPL, MSFT`, naming at most five tickers."""
    shown = ", ".join(quote.ticker for quote in quotes[:_TITLED_TICKERS])
    rest = len(quotes) - _TITLED_TICKERS
    return f"IEX top of book: {shown} and {rest} more" if rest > 0 else f"IEX top of book: {shown}"
