# mcp-scaffold-commit: 36a912c54836, timestamp: 2026-10-29T08:37:43+00:00

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import override

import asyncpg
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.postgresql import PostgreSQLStore
from mcp_configs import PostgresSettings

# The connection every MCP shares: DATABASE_URL or DB_*, with the chart's TLS settings.
StoreSettings = PostgresSettings
# `Persistence.store`: a key-value store with `get`, `put`, `delete` and a TTL per entry. Typed
# as the protocol rather than PostgreSQLStore, so the tests can hand in a MemoryStore.
Store = AsyncKeyValue


class _PostgresStore(PostgreSQLStore):
    """A `PostgreSQLStore` that connects as `PostgresSettings` says.

    The store takes a URL alone, which drops the chart's `PG_DATABASE_SSL_MODE` and CA: a
    CloudNativePG URL has no `sslmode`. The pool stays small, as asyncpg's default of ten
    connections per store would be twenty per pod.
    """

    _settings: StoreSettings
    _dsn: str

    def __init__(self, settings: StoreSettings) -> None:
        dsn = settings.connection_url.replace("postgresql+asyncpg", "postgresql", 1)
        super().__init__(url=dsn)
        self._settings = settings
        self._dsn = dsn

    @override
    async def _create_pool(self) -> asyncpg.Pool:
        # asyncpg's pool is partly untyped, as the store's own calls to it show.
        return await asyncpg.create_pool(  # pyright: ignore[reportUnknownMemberType]
            self._dsn, min_size=1, max_size=self._settings.pool_size, **self._settings.connect_args
        )


@asynccontextmanager
async def open_store(settings: StoreSettings) -> AsyncGenerator[Store]:
    async with _PostgresStore(settings) as store:
        yield store


def sign_in_store(settings: StoreSettings) -> Store:
    """Where the auth provider keeps its clients and tokens, so a sign-in survives a restart and
    reaches every replica.

    The provider exists before the lifespan opens `Persistence`, so it gets a store of its own
    that lives as long as the process.
    """
    return _PostgresStore(settings)
