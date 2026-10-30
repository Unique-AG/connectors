# mcp-scaffold-commit: 36a912c54836, timestamp: 2026-10-29T08:37:43+00:00

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import ClassVar

from mcp_configs import from_environment
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from world_check_mcp.persistence.store import open_store
from world_check_mcp.persistence.store import Store
from world_check_mcp.persistence.store import StoreSettings


class PersistenceSettings(BaseModel):
    """Each store reads its own settings from the environment."""

    store: StoreSettings = Field(default_factory=lambda: from_environment(StoreSettings))


class Persistence(BaseModel):
    """What the contexts receive: every store the MCP owns, opened once by the server lifespan."""

    model_config: ClassVar[ConfigDict] = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    store: Store


@asynccontextmanager
async def open_persistence(settings: PersistenceSettings) -> AsyncGenerator[Persistence]:
    async with (
        open_store(settings.store) as store,
    ):
        yield Persistence(store=store)
