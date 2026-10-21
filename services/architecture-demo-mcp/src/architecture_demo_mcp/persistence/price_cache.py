from collections.abc import Sequence
from typing import cast

from pydantic import BaseModel

from architecture_demo_mcp.persistence.persistence import Persistence


async def cached_price_history[M: BaseModel](
    *, persistence: Persistence, key: str, model: type[M]
) -> list[M] | None:
    """None when nothing is cached under `key`, an empty list when an empty history is."""
    value = await persistence.store.get(key, collection=_COLLECTION)
    if value is None:
        return None
    return [model.model_validate(bar) for bar in cast(list[object], value[_BARS])]


async def cache_price_history(
    *, persistence: Persistence, key: str, bars: Sequence[BaseModel]
) -> None:
    await persistence.store.put(
        key,
        {_BARS: [bar.model_dump(mode="json") for bar in bars]},
        collection=_COLLECTION,
        ttl=_TTL_SECONDS,
    )


_COLLECTION = "price-history"
# A store entry is a mapping, so the list sits under one key.
_BARS = "bars"
# Tiingo publishes end-of-day prices once a day and limits requests per hour.
_TTL_SECONDS = 15 * 60
