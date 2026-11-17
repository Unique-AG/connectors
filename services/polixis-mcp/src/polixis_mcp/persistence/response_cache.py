import asyncio
import logging

from polixis_mcp.persistence.persistence import Persistence

_logger = logging.getLogger(__name__)


async def cached_response(*, persistence: Persistence, key: str) -> dict[str, object] | None:
    """None when the cache is off, as when nothing is cached under `key`."""
    cache = persistence.response_cache
    if not cache.enabled:
        return None
    return await persistence.store.get(f"{cache.key_prefix}:{key}", collection=_COLLECTION)


async def cache_response(
    *, persistence: Persistence, key: str, response: dict[str, object]
) -> None:
    cache = persistence.response_cache
    if cache.enabled:
        await persistence.store.put(
            f"{cache.key_prefix}:{key}", response, collection=_COLLECTION, ttl=cache.ttl_seconds
        )


async def cull_expired_entries_periodically(persistence: Persistence) -> None:
    """Deletes the store's expired entries now and once per cache TTL after, until cancelled, so
    no cached answer stays in Postgres longer than twice the TTL. It runs with the cache off too,
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
