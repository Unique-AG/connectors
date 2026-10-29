# mcp-scaffold-commit: 36a912c54836, timestamp: 2026-10-29T08:37:43+00:00

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.redis import RedisStore
from mcp_configs import RedisSettings

# The connection every MCP shares: REDIS_URL.
StoreSettings = RedisSettings
# `Persistence.store`: a key-value store with `get`, `put`, `delete` and a TTL per entry. Typed
# as the protocol rather than RedisStore, so the tests can hand in a MemoryStore.
Store = AsyncKeyValue


@asynccontextmanager
async def open_store(settings: StoreSettings) -> AsyncGenerator[Store]:
    async with RedisStore(url=settings.url.get_secret_value()) as store:
        yield store


def sign_in_store(settings: StoreSettings) -> Store:
    """Where the auth provider keeps its clients and tokens, so a sign-in survives a restart and
    reaches every replica.

    The provider exists before the lifespan opens `Persistence`, so it gets a store of its own
    that lives as long as the process.
    """
    return RedisStore(url=settings.url.get_secret_value())
