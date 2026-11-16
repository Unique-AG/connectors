# mcp-scaffold-commit: 6474bb8667dc, timestamp: 2026-11-16T10:36:30+00:00

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import ClassVar

import httpx2
from key_value.aio.stores.postgresql import PostgreSQLStore
from mcp_configs import from_environment
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from kyckr_mcp.persistence.store import StoreSettings


class PersistenceSettings(BaseModel):
    """Each store reads its own settings from the environment."""

    store: StoreSettings = Field(default_factory=lambda: from_environment(StoreSettings))

    def passwords(self) -> tuple[str, ...]:
        password = httpx2.URL(self.store.connection_url).password
        return (password,) if password else ()


class Persistence(BaseModel):
    """What the contexts receive. Empty: no context stores anything yet."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)


@asynccontextmanager
async def open_persistence(sign_in: PostgreSQLStore | None = None) -> AsyncGenerator[Persistence]:
    """Closes the sign-in store's pool, if it opened one, when the server stops."""
    try:
        yield Persistence()
    finally:
        if sign_in is not None:
            await sign_in.close()
