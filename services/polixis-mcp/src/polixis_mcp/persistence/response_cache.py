import asyncio
import logging

from polixis_mcp.persistence.persistence import Persistence

_logger = logging.getLogger(__name__)


async def cached_response(*, persistence: Persistence, key: str) -> dict[str, object] | None:
    return await persistence.store.get(key, collection=_COLLECTION)


async def cache_response(
    *, persistence: Persistence, key: str, response: dict[str, object]
) -> None:
    await persistence.store.put(key, response, collection=_COLLECTION, ttl=_TTL_SECONDS)


async def cull_expired_entries_periodically(persistence: Persistence) -> None:
    """Deletes the store's expired entries now and every few hours after, until cancelled. A
    failed run is logged and the next one tries again: it runs in the server lifespan's task
    group, where an error that escapes would stop the server over rows that only stay longer.
    """
    while True:
        try:
            await persistence.store.cull()
        except Exception:
            _logger.warning("Could not delete the expired store entries", exc_info=True)
        await asyncio.sleep(_CULL_EVERY_SECONDS)


_COLLECTION = "polixis-responses"
# Long enough for an agent to page through a result and ask the next question about the same
# entity, short enough that a change at Polixis shows within minutes.
_TTL_SECONDS = 5 * 60
_CULL_EVERY_SECONDS = 4 * 60 * 60
