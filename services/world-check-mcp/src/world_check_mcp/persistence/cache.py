from collections.abc import Awaitable, Callable
import logging

from pydantic import TypeAdapter

from world_check_mcp.persistence.store import Store

_COLLECTION = "cache"
_logger = logging.getLogger(__name__)


class Cache:
    """Configuration LSEG hands every caller alike, kept for a while in the store.

    Never for a case or a person. A value is kept as a JSON string: Postgres keeps an object as
    JSONB and sorts its keys, which would reorder a list LSEG sent as a map. It is not the store
    itself: the store closes its connections when it is exited, and FastMCP exits what a
    dependency returns when it is a context manager.
    """

    _store: Store

    def __init__(self, store: Store) -> None:
        self._store = store

    async def read_through[Value](
        self,
        *,
        key: str,
        adapter: TypeAdapter[Value],
        ttl_seconds: float,
        load: Callable[[], Awaitable[Value]],
    ) -> Value:
        """The cached value for `key`, or what `load` returns, kept for `ttl_seconds`.

        A cache that cannot be read or written only costs a call to LSEG, and a value saved by an
        older version that no longer validates is loaded again.
        """
        try:
            stored = await self._store.get(key, collection=_COLLECTION)
            held = None if stored is None else stored.get("value")
            if isinstance(held, str):
                return adapter.validate_json(held)
        except Exception:  # noqa: BLE001 - an unreadable cache entry is loaded again
            _logger.exception("Cache read failed", extra={"cache_key": key})
        value = await load()
        try:
            await self._store.put(
                key,
                {"value": adapter.dump_json(value, by_alias=True).decode()},
                collection=_COLLECTION,
                ttl=ttl_seconds,
            )
        except Exception:  # noqa: BLE001 - the value is still good without a cache entry
            _logger.exception("Cache write failed", extra={"cache_key": key})
        return value

    async def forget(self, key: str) -> None:
        """Drops `key`, so the next read loads it again."""
        try:
            await self._store.delete(key, collection=_COLLECTION)
        except Exception:  # noqa: BLE001 - an entry that cannot be dropped still expires
            _logger.exception("Cache delete failed", extra={"cache_key": key})
