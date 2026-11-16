# mcp-scaffold-commit: 6474bb8667dc, timestamp: 2026-11-16T10:36:30+00:00

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import ClassVar

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from sqlalchemy import make_url

from kyckr_mcp.persistence.database import Database
from kyckr_mcp.persistence.database import DatabaseSettings
from kyckr_mcp.persistence.database import open_database


class PersistenceSettings(BaseModel):
    """Each store reads its own settings from the environment."""

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)

    def passwords(self) -> tuple[str, ...]:
        password = make_url(self.database.connection_url).password
        return (password,) if password else ()


class Persistence(BaseModel):
    """What the contexts receive: every store the MCP owns, opened once by the server lifespan."""

    model_config: ClassVar[ConfigDict] = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    database: Database


@asynccontextmanager
async def open_persistence(settings: PersistenceSettings) -> AsyncGenerator[Persistence]:
    async with (
        open_database(settings.database) as database,
    ):
        yield Persistence(database=database)
