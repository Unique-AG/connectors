"""Storage the MCP owns: a file-backed JSON snapshot store.

Expose the store's interface here, never its driver: contexts depend on what is stored,
not where.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from space_config_mcp.persistence.settings import PersistenceSettings
from space_config_mcp.persistence.store import Persistence


@asynccontextmanager
async def open_persistence(
    settings: PersistenceSettings,
) -> AsyncGenerator[Persistence]:
    yield Persistence(settings.snapshot_store_path)


__all__ = ["open_persistence", "Persistence", "PersistenceSettings"]
