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

from polixis_mcp.persistence.database import create_database
from polixis_mcp.persistence.database import Database
from polixis_mcp.persistence.database import DatabaseSettings
from polixis_mcp.persistence.database import open_database
from polixis_mcp.persistence.response_cache import PostgresResponseCache
from polixis_mcp.persistence.response_cache import ResponseCacheStore
from polixis_mcp.persistence.store import PostgresSignInStateTable
from polixis_mcp.persistence.store import SignInStateTable

_logger = logging.getLogger(__name__)


class PersistenceSettings(BaseModel):
    """Each store reads its own settings from the environment."""

    database: DatabaseSettings = Field(default_factory=lambda: from_environment(DatabaseSettings))


class Persistence(BaseModel):
    """Every store the MCP owns, over one `database`. It exists before the server, since the
    upstream client caches Polixis's answers in `response_cache`; the server lifespan opens and
    closes it. `sign_in_state` is the key-value table the auth provider's own store writes, kept
    here so its expired rows are culled.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    database: Database
    response_cache: ResponseCacheStore
    sign_in_state: SignInStateTable


def create_persistence(settings: PersistenceSettings) -> Persistence:
    database = create_database(settings.database)
    return Persistence(
        database=database,
        response_cache=PostgresResponseCache(database),
        sign_in_state=PostgresSignInStateTable(database),
    )


@asynccontextmanager
async def open_persistence(persistence: Persistence) -> AsyncGenerator[None]:
    async with open_database(persistence.database):
        yield


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
            await persistence.sign_in_state.cull()
            await persistence.response_cache.cull(max_bytes=max_cache_bytes)
        except Exception:
            _logger.warning("Could not delete the expired store entries", exc_info=True)
        await asyncio.sleep(every)
