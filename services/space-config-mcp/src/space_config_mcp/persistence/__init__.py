"""Storage the MCP owns: a content-store-backed snapshot history.

Each snapshot is stored as an application/json blob in the platform
knowledge base under a hidden folder, so it persists across restarts
and is visible to space managers in the file browser.

Expose the store's interface here, never its driver: contexts depend on
what is stored, not where.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from space_config_mcp.persistence.settings import PersistenceSettings
from space_config_mcp.persistence.store import Persistence


@asynccontextmanager
async def open_persistence(
    settings: PersistenceSettings,
) -> AsyncGenerator[Persistence]:
    yield Persistence(settings)


__all__ = ["open_persistence", "Persistence", "PersistenceSettings"]
