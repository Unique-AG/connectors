from collections.abc import Awaitable, Callable
import logging

from pydantic import TypeAdapter

from world_check_mcp.persistence.store import Store

_COLLECTION = "cache"
_logger = logging.getLogger(__name__)


class Cache:
    """Configuration LSEG hands every caller alike, kept for a while in the store.

    Never for a case or a person. It is not the store itself: the store closes its connections
    when it is exited, and FastMCP exits what a dependency returns when it is a context manager.
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
            if stored is not None:
                return adapter.validate_python(stored["value"])
        except Exception:  # noqa: BLE001 - an unreadable cache entry is loaded again
            _logger.exception("Cache read failed", extra={"cache_key": key})
        value = await load()
        try:
            await self._store.put(
                key,
                {"value": adapter.dump_python(value, mode="json")},
                collection=_COLLECTION,
                ttl=ttl_seconds,
            )
        except Exception:  # noqa: BLE001 - the value is still good without a cache entry
            _logger.exception("Cache write failed", extra={"cache_key": key})
        return value
