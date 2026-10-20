from collections.abc import Mapping, Sequence

from pydantic import BaseModel

from architecture_demo_mcp.persistence.persistence import Persistence


async def cached_quotes[Q: BaseModel](
    *, persistence: Persistence, tickers: Sequence[str], model: type[Q]
) -> dict[str, Q]:
    """The cached quote of each ticker that has one."""
    values = await persistence.store.get_many(tickers, collection=_COLLECTION)
    return {
        ticker: model.model_validate(value)
        for ticker, value in zip(tickers, values, strict=True)
        if value is not None
    }


async def cache_quotes(*, persistence: Persistence, quotes: Mapping[str, BaseModel]) -> None:
    if not quotes:
        return
    await persistence.store.put_many(
        list(quotes),
        [quote.model_dump(mode="json") for quote in quotes.values()],
        collection=_COLLECTION,
        ttl=_TTL_SECONDS,
    )


_COLLECTION = "quotes"
# Tiingo limits requests per hour, and a quote a minute old still says what a ticker trades at.
_TTL_SECONDS = 60
