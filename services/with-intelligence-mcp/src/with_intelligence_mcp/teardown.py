"""Release resources and clear cached providers."""

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
from with_intelligence_mcp.features.wi_session import get_wi_session_cache


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
    get_wi_session_cache,
)


async def close_singletons() -> None:
    try:
        await _release_pools()
    finally:
        for provider in PROVIDERS:
            provider.cache_clear()


async def _release_pools() -> None:
    """Release initialized resource pools."""
    try:
        if get_with_intelligence_client_factory.cache_info().currsize:
            await get_with_intelligence_client_factory().aclose()
    finally:
        if get_engine.cache_info().currsize:
            await get_engine().dispose()
