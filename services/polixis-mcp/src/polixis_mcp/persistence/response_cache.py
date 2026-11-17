import asyncio
from datetime import datetime
from datetime import timedelta
from datetime import UTC
import logging

from pydantic import AwareDatetime
from pydantic import BaseModel
from pydantic import ValidationError

from polixis_mcp.persistence.persistence import Persistence

_logger = logging.getLogger(__name__)


class CachedResponse(BaseModel):
    """A Polixis answer as the cache holds it, with when it was cached."""

    cached_at: AwareDatetime
    response: dict[str, object]


async def cached_response(*, persistence: Persistence, key: str) -> CachedResponse | None:
    """None when the cache is off, when nothing is cached under `key`, and for an entry cached
    in an older form or longer ago than the TTL now set, as after a restart with a shorter one,
    which is then fetched again.
    """
    cache = persistence.response_cache
    if not cache.enabled:
        return None
    entry = await persistence.store.get(f"{cache.key_prefix}:{key}", collection=_COLLECTION)
    if entry is None:
        return None
    try:
        cached = CachedResponse.model_validate(entry)
    except ValidationError:
        return None
    if datetime.now(UTC) - cached.cached_at > timedelta(seconds=cache.ttl_seconds):
        return None
    return cached


async def cache_response(
    *, persistence: Persistence, key: str, response: dict[str, object]
) -> None:
    cache = persistence.response_cache
    if cache.enabled:
        entry = CachedResponse(cached_at=datetime.now(UTC), response=response)
        await persistence.store.put(
            f"{cache.key_prefix}:{key}",
            entry.model_dump(mode="json"),
            collection=_COLLECTION,
            ttl=cache.ttl_seconds,
        )


async def cull_expired_entries_periodically(persistence: Persistence) -> None:
    """Deletes the store's expired entries now and once per cache TTL after, until cancelled, so
    a cached answer normally leaves Postgres within twice the TTL it was cached with; a failed run
    or a shorter TTL set since can leave it longer. It runs with the cache off too,
    to delete what was cached before. A failed run is logged and the next one tries again: it
    runs in the server lifespan's task group, where an error that escapes would stop the server
    over rows that only stay longer.
    """
    while True:
        try:
            await persistence.store.cull()
        except Exception:
            _logger.warning("Could not delete the expired store entries", exc_info=True)
        await asyncio.sleep(persistence.response_cache.ttl_seconds)


_COLLECTION = "polixis-responses"
