# mcp-scaffold-commit: 36a912c54836, timestamp: 2026-10-29T08:37:43+00:00

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import override

import asyncpg
import httpx2
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.postgresql import PostgreSQLStore
from mcp_configs import PostgresSettings

StoreSettings = PostgresSettings
Store = AsyncKeyValue

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

    def __init__(self, settings: StoreSettings) -> None:
        dsn, statement_cache_size = _asyncpg_dsn(settings.connection_url)
        super().__init__(url=dsn)
        self._settings = settings
        self._dsn = dsn
        self._statement_cache_size = statement_cache_size

    @override
    async def _create_pool(self) -> asyncpg.Pool:
        return await asyncpg.create_pool(  # pyright: ignore[reportUnknownMemberType]
            self._dsn,
            min_size=1,
            max_size=self._settings.pool_size,
            statement_cache_size=self._statement_cache_size,
            **self._settings.connect_args,
        )


@asynccontextmanager
async def open_store(settings: StoreSettings) -> AsyncGenerator[Store]:
    async with _PostgresStore(settings) as store:
        yield store


def sign_in_store(settings: StoreSettings) -> Store:
    """The auth provider's own store: it exists before the lifespan opens `Persistence`."""
    return _PostgresStore(settings)
