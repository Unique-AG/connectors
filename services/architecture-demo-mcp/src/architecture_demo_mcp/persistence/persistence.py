from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import ClassVar

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from architecture_demo_mcp.persistence.database import Database
from architecture_demo_mcp.persistence.database import DatabaseSettings
from architecture_demo_mcp.persistence.database import open_database
from architecture_demo_mcp.persistence.store import open_store
from architecture_demo_mcp.persistence.store import Store
from architecture_demo_mcp.persistence.store import StoreSettings


def _store_settings() -> StoreSettings:
    return StoreSettings()  # pyright: ignore[reportCallIssue]


class PersistenceSettings(BaseModel):
    """Each store reads its own settings from the environment."""

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    store: StoreSettings = Field(default_factory=_store_settings)


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
