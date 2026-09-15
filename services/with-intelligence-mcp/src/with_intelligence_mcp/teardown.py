"""Release resources and clear cached providers."""

from typing import Protocol

from with_intelligence_mcp.dependencies import (
    get_app_config,
    get_database_config,
    get_engine,
    get_session_factory,
    get_with_intelligence_config,
)


class CachedProvider(Protocol):
    """What a teardown needs of an `@lru_cache(maxsize=1)` provider."""

    def cache_clear(self) -> None: ...


PROVIDERS: tuple[CachedProvider, ...] = (
    get_app_config,
    get_with_intelligence_config,
    get_database_config,
    get_engine,
    get_session_factory,
)


async def close_singletons() -> None:
    """Release the pooled resources, then drop every cached provider."""
    try:
        await _release_pools()
    finally:
        for provider in PROVIDERS:
            provider.cache_clear()


async def _release_pools() -> None:
    """Dispose the engine pool if it was created."""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
