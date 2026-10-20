from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.redis import RedisStore
from mcp_runtime import RedisSettings

# The connection every MCP shares: REDIS_URL.
StoreSettings = RedisSettings
# `Persistence.store`: a key-value store with `get`, `put`, `delete` and a TTL per entry. Typed
# as the protocol rather than RedisStore, so the tests can hand in a MemoryStore.
Store = AsyncKeyValue


@asynccontextmanager
async def open_store(settings: StoreSettings) -> AsyncGenerator[Store]:
    async with RedisStore(url=settings.url.get_secret_value()) as store:
        yield store
