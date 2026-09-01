"""Releasing what the cached providers hold, and dropping every one of them.

`PROVIDERS` is the whole of what a teardown clears; `tests/test_teardown.py` fails when it and
the provider modules disagree.
"""

from typing import Protocol

from with_intelligence_mcp.dependencies import (
    get_app_config,
    get_auth_config,
    get_auth_context,
    get_auth_provider,
    get_database_config,
    get_encryption_config,
    get_encryption_key,
    get_engine,
    get_session_factory,
    get_with_intelligence_client_factory,
    get_with_intelligence_config,
)
from with_intelligence_mcp.features.vendor_session import get_vendor_session_registry


class CachedProvider(Protocol):
    def cache_clear(self) -> None: ...


PROVIDERS: tuple[CachedProvider, ...] = (
    get_app_config,
    get_with_intelligence_config,
    get_database_config,
    get_auth_config,
    get_encryption_config,
    get_engine,
    get_session_factory,
    get_encryption_key,
    get_with_intelligence_client_factory,
    get_auth_context,
    get_auth_provider,
    get_vendor_session_registry,
)


async def close_singletons() -> None:
    try:
        await _release_pools()
    finally:
        for provider in PROVIDERS:
            provider.cache_clear()


async def _release_pools() -> None:
    # Each only if it was ever built: constructing one here would read config a test never set.
    # The engine is disposed even if closing the HTTP pool fails — an undisposed pool bound to a
    # dead event loop is what the next `create_app` trips over.
    try:
        if get_with_intelligence_client_factory.cache_info().currsize:
            await get_with_intelligence_client_factory().aclose()
    finally:
        if get_engine.cache_info().currsize:
            await get_engine().dispose()
