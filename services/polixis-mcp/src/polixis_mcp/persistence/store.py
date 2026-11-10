# mcp-scaffold-commit: 36a912c54836, timestamp: 2026-10-29T08:37:43+00:00

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import override, Protocol

import asyncpg
import httpx2
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.protocols.key_value import AsyncCullProtocol
from key_value.aio.stores.postgresql import PostgreSQLStore
from mcp_configs import PostgresSettings

StoreSettings = PostgresSettings


class Store(AsyncKeyValue, AsyncCullProtocol, Protocol):
    """A key-value store whose `cull` deletes the entries past their TTL."""


# PostgreSQLStore's default table, named here so the cull does not read its private name.
_TABLE = "kv_store"
_DELETE_EXPIRED = f"DELETE FROM {_TABLE} WHERE expires_at <= now()"
_SQLALCHEMY_ONLY = "prepared_statement_cache_size"
_ASYNCPG_DEFAULT_CACHE = 100


def _asyncpg_dsn(url: str) -> tuple[str, int]:
    """The DSN without the SQLAlchemy-only cache option, and that option as asyncpg's argument."""
    parsed = httpx2.URL(url.replace("postgresql+asyncpg", "postgresql", 1))
    cache_size = parsed.params.get(_SQLALCHEMY_ONLY) or str(_ASYNCPG_DEFAULT_CACHE)
    dsn = str(parsed.copy_remove_param(_SQLALCHEMY_ONLY))
    return dsn, int(cache_size)


class _PostgresStore(PostgreSQLStore):
    """A `PostgreSQLStore` that connects as `PostgresSettings` says: with its TLS settings and a
    small pool.
    """

    _settings: StoreSettings
    _dsn: str
    _statement_cache_size: int
    _cull_pool: asyncpg.Pool | None

    def __init__(self, settings: StoreSettings) -> None:
        dsn, statement_cache_size = _asyncpg_dsn(settings.connection_url)
        super().__init__(url=dsn, table_name=_TABLE)
        self._settings = settings
        self._dsn = dsn
        self._statement_cache_size = statement_cache_size
        self._cull_pool = None

    @override
    async def _create_pool(self) -> asyncpg.Pool:
        pool = await asyncpg.create_pool(  # pyright: ignore[reportUnknownMemberType]
            self._dsn,
            min_size=1,
            max_size=self._settings.pool_size,
            statement_cache_size=self._statement_cache_size,
            **self._settings.connect_args,
        )
        self._cull_pool = pool
        return pool

    async def cull(self) -> None:
        """Deletes every entry past its TTL. `PostgreSQLStore` only hides one when it is read, so
        its row stays until this runs.
        """
        assert self._cull_pool is not None, "cull runs once the store is open"
        await self._cull_pool.execute(_DELETE_EXPIRED)  # pyright: ignore[reportUnknownMemberType] - asyncpg's Pool.execute is untyped


@asynccontextmanager
async def open_store(settings: StoreSettings) -> AsyncGenerator[Store]:
    async with _PostgresStore(settings) as store:
        yield store


def sign_in_store(settings: StoreSettings) -> Store:
    """The auth provider's own store: it exists before the lifespan opens `Persistence`."""
    return _PostgresStore(settings)
