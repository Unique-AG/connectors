# mcp-scaffold-commit: 36a912c54836, timestamp: 2026-10-29T08:37:43+00:00

from typing import override, Protocol, runtime_checkable

import asyncpg
import httpx2
from key_value.aio.stores.postgresql import PostgreSQLStore
from mcp_configs import PostgresSettings
from sqlalchemy import delete
from sqlalchemy import func

from polixis_mcp.persistence.database import Database
from polixis_mcp.persistence.models import KeyValueRow

StoreSettings = PostgresSettings

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
    small pool. It does not make its table, which a migration makes, and fails to set up without
    it.
    """

    _settings: StoreSettings
    _dsn: str
    _statement_cache_size: int

    def __init__(self, settings: StoreSettings) -> None:
        dsn, statement_cache_size = _asyncpg_dsn(settings.connection_url)
        super().__init__(url=dsn, table_name=KeyValueRow.__tablename__, auto_create=False)
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


def postgres_store(settings: StoreSettings) -> PostgreSQLStore:
    """The auth provider's store for the sign-in state. Not connected yet: it connects on first
    use, or on `setup`.
    """
    return _PostgresStore(settings)


@runtime_checkable
class SignInStateTable(Protocol):
    async def cull(self) -> None:
        """Deletes every entry past its TTL. `PostgreSQLStore` only hides one when it is read,
        so its row stays until this runs.
        """
        ...


class PostgresSignInStateTable:
    """The table the auth provider's store keeps the sign-in state in, culled through the MCP's
    own database rather than a pool of the store's.
    """

    def __init__(self, database: Database) -> None:
        self._database: Database = database

    async def cull(self) -> None:
        async with self._database.begin() as session:
            await session.execute(delete(KeyValueRow).where(KeyValueRow.expires_at <= func.now()))
