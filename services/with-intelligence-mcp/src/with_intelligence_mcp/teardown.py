"""Releasing what the cached providers hold, and dropping every one of them.

`PROVIDERS` is the whole of what a teardown clears; `tests/test_teardown.py` fails when it and
`dependencies` disagree.
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
    def cache_clear(self) -> None: ...


PROVIDERS: tuple[CachedProvider, ...] = (
    get_app_config,
    get_with_intelligence_config,
    get_database_config,
    get_engine,
    get_session_factory,
)


async def close_singletons() -> None:
    try:
        await _release_pools()
    finally:
        for provider in PROVIDERS:
            provider.cache_clear()


async def _release_pools() -> None:
    # Only if one was ever built: constructing it here would read config a test never set.
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
