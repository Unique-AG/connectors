# mcp-scaffold-commit: f07e25a209f4, timestamp: 2026-11-09T11:34:03+00:00

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import logging
from typing import ClassVar

from mcp_configs import from_environment
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from polixis_mcp.persistence.database import create_engine
from polixis_mcp.persistence.database import DatabaseSettings
from polixis_mcp.persistence.response_cache import PostgresResponseCache
from polixis_mcp.persistence.response_cache import ResponseCacheStore
from polixis_mcp.persistence.store import postgres_store
from polixis_mcp.persistence.store import Store
from polixis_mcp.persistence.store import StoreSettings

_logger = logging.getLogger(__name__)


class PersistenceSettings(BaseModel):
    """Each store reads its own settings from the environment."""

    database: DatabaseSettings = Field(default_factory=lambda: from_environment(DatabaseSettings))
    store: StoreSettings = Field(default_factory=lambda: from_environment(StoreSettings))


class Persistence(BaseModel):
    """Every store the MCP owns. It exists before the server, since the upstream client caches
    Polixis's answers in `response_cache`; the server lifespan opens and closes it. `store` is
    the key-value table the sign-in state shares, kept here so its expired rows are culled.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    store: Store
    response_cache: ResponseCacheStore


def create_persistence(settings: PersistenceSettings) -> Persistence:
    return Persistence(
        store=postgres_store(settings.store),
        response_cache=PostgresResponseCache(create_engine(settings.database)),
    )


@asynccontextmanager
async def open_persistence(persistence: Persistence) -> AsyncGenerator[None]:
    """Connects now, so a database the server cannot reach stops it from starting."""
    await persistence.store.setup()
    try:
        await persistence.response_cache.setup()
        try:
            yield
        finally:
            await persistence.response_cache.close()
    finally:
        await persistence.store.close()


async def cull_expired_entries_periodically(
    persistence: Persistence, *, every: float, max_cache_bytes: int
) -> None:
    """Deletes the expired entries now and once per `every` seconds after, until cancelled, and
    the least recently used cached answers past `max_cache_bytes`. It runs with the cache off
    too, to delete what was cached before. A failed run is logged and the next one tries again:
    it runs in the server lifespan's task group, where an error that escapes would stop the
    server over rows that only stay longer.
    """
    while True:
        try:
            await persistence.store.cull()
            await persistence.response_cache.cull(max_bytes=max_cache_bytes)
        except Exception:
            _logger.warning("Could not delete the expired store entries", exc_info=True)
        await asyncio.sleep(every)
