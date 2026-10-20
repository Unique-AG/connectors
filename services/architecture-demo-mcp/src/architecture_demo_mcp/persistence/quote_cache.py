from pydantic import BaseModel

from architecture_demo_mcp.persistence.persistence import Persistence


async def cached_quote[Q: BaseModel](
    *, persistence: Persistence, ticker: str, model: type[Q]
) -> Q | None:
    value = await persistence.store.get(ticker, collection=_COLLECTION)
    return None if value is None else model.model_validate(value)


async def cache_quote(*, persistence: Persistence, ticker: str, quote: BaseModel) -> None:
    await persistence.store.put(
        ticker, quote.model_dump(mode="json"), collection=_COLLECTION, ttl=_TTL_SECONDS
    )


_COLLECTION = "quotes"
# Tiingo limits requests per hour, and a quote a minute old still says what a ticker trades at.
_TTL_SECONDS = 60
