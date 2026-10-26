# mcp-scaffold-commit: 9a91a8864afe, timestamp: 2026-10-21T12:09:32+00:00

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import ClassVar

from mcp_configs import from_environment
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from architecture_demo_mcp.persistence.database import Database
from architecture_demo_mcp.persistence.database import DatabaseSettings
from architecture_demo_mcp.persistence.database import open_database
from architecture_demo_mcp.persistence.store import open_store
from architecture_demo_mcp.persistence.store import Store
from architecture_demo_mcp.persistence.store import StoreSettings


class PersistenceSettings(BaseModel):
    """Each store reads its own settings from the environment."""

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    store: StoreSettings = Field(default_factory=lambda: from_environment(StoreSettings))


class Persistence(BaseModel):
    """What the contexts receive: every store the MCP owns, opened once by the server lifespan."""

    model_config: ClassVar[ConfigDict] = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    database: Database
    store: Store


@asynccontextmanager
async def open_persistence(settings: PersistenceSettings) -> AsyncGenerator[Persistence]:
    async with (
        open_database(settings.database) as database,
        open_store(settings.store) as store,
    ):
        yield Persistence(database=database, store=store)
