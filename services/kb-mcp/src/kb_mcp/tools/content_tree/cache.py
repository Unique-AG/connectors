import asyncio
import logging

from unique_toolkit.experimental.resources.feature_flags._ttl_cache import (
    AsyncTTLCache,
)
from unique_toolkit.monitoring.memory import trim_memory

from kb_mcp.settings import Settings

_LOGGER = logging.getLogger(__name__)
_TREE_CACHE_EXPIRE_INTERVAL_SECONDS = 30.0

_tree_cache: AsyncTTLCache | None = None


def get_tree_cache(settings: Settings) -> AsyncTTLCache:
    global _tree_cache
    if _tree_cache is None:
        _tree_cache = AsyncTTLCache(
            maxsize=settings.content_tree_cache_max_entries,
            ttl_ms=settings.content_tree_cache_ttl_seconds * 1000,
            keep_stale=False,
        )
    return _tree_cache


def expire_idle_trees() -> int:
    cache = _tree_cache
    if cache is None:
        return 0
    expired = cache._cache.expire()  # pyright: ignore[reportPrivateUsage]
    dropped = len(expired)
    del expired
    return dropped


async def expire_idle_trees_loop(
    interval_seconds: float = _TREE_CACHE_EXPIRE_INTERVAL_SECONDS,
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            dropped = expire_idle_trees()
            if dropped:
                trim_memory("tree-cache-expire")
        except Exception:
            _LOGGER.exception("tree-cache expire cycle failed")
