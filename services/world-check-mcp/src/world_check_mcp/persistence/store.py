from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.redis import RedisStore
from mcp_configs import RedisSettings

# The connection every MCP shares: REDIS_URL.
StoreSettings = RedisSettings
# A key-value store with `get`, `put`, `delete` and a TTL per entry. Typed as the protocol
# rather than RedisStore, so a test can hand in a MemoryStore.
Store = AsyncKeyValue


def sign_in_store(settings: StoreSettings) -> Store:
    """Where the auth provider keeps its clients and tokens, so a sign-in survives a restart and
    reaches every replica.

    The provider exists before the server lifespan, so it gets a store of its own that lives as
    long as the process.
    """
    return RedisStore(url=settings.url.get_secret_value())
