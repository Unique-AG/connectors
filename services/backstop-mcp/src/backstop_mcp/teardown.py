"""Releasing what the cached providers hold, and dropping every one of them.

Separate from `dependencies.py` so the feature-owned providers can be imported at module level.
`features/<f>/dependencies.py` imports `backstop_mcp.dependencies`, so the root module importing
those features back would be an import cycle — the shape rules 1 and 2 in `tests/test_layering.py`
exist to keep out. Nothing under `features/` imports this module, so the direction stays one-way.

`PROVIDERS` is the whole of what a teardown clears. Adding a cached provider and forgetting to
list it here leaks a stale singleton into the next `create_app` — and, in the suite, into the
next test. `tests/test_teardown.py` fails when the two disagree.
"""

from typing import Protocol

from backstop_mcp.dependencies import (
    get_activity_history_config,
    get_app_config,
    get_auth_config,
    get_auth_provider,
    get_backstop_client_factory,
    get_backstop_config,
    get_database_config,
    get_encryption_config,
    get_encryption_key,
    get_engine,
    get_session_factory,
)
from backstop_mcp.features.activity_history import get_activity_history_settings
from backstop_mcp.features.activity_tags import get_activity_tags_service
from backstop_mcp.features.custom_fields import (
    get_custom_field_groups_service,
    get_custom_fields_service,
)
from backstop_mcp.features.data_hygiene import get_employment_index_factory
from backstop_mcp.features.opportunities import get_opportunity_stages_service


class CachedProvider(Protocol):
    """What a teardown needs of an `@lru_cache(maxsize=1)` provider."""

    def cache_clear(self) -> None: ...


PROVIDERS: tuple[CachedProvider, ...] = (
    get_app_config,
    get_backstop_config,
    get_database_config,
    get_encryption_config,
    get_auth_config,
    get_activity_history_config,
    get_engine,
    get_session_factory,
    get_encryption_key,
    get_backstop_client_factory,
    get_auth_provider,
    get_activity_history_settings,
    get_activity_tags_service,
    get_custom_fields_service,
    get_custom_field_groups_service,
    get_employment_index_factory,
    get_opportunity_stages_service,
)


async def close_singletons() -> None:
    """Release the pooled resources, then drop every cached provider."""
    try:
        await _release_pools()
    finally:
        for provider in PROVIDERS:
            provider.cache_clear()


async def _release_pools() -> None:
    """Close the client factory's connection pool, then the engine's.

    Each is closed only if it was ever built: constructing one here just to close it would read
    configuration a test may never have set. The engine is disposed even when closing the factory
    fails — an undisposed pool bound to a dead event loop is what the next `create_app` (or the
    next test) trips over, so it must not depend on the first close succeeding.
    """
    try:
        if get_backstop_client_factory.cache_info().currsize:
            await get_backstop_client_factory().aclose()
    finally:
        if get_engine.cache_info().currsize:
            await get_engine().dispose()
