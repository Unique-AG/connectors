"""Releasing what the cached providers hold, and dropping every one of them.

Separate from `dependencies.py` so feature-owned providers can be imported at module level once
they exist: `features/<f>/dependencies.py` imports `with_intelligence_mcp.dependencies`, so the
root module importing those features back would be an import cycle. Nothing under `features/`
imports this module, so the direction stays one-way.

`PROVIDERS` is the whole of what a teardown clears. Adding a cached provider and forgetting to
list it here leaks a stale singleton into the next `create_app` — and, in the suite, into the
next test. `tests/test_teardown.py` fails when the two disagree.
"""

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
    """Dispose the engine's connection pool, if one was ever built.

    Constructing it here just to close it would read configuration a test may never have set —
    hence the `cache_info()` check rather than an unconditional call. An undisposed pool bound
    to a dead event loop is what the next `create_app` (or the next test) trips over.
    """
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
