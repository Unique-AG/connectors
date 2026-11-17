# mcp-scaffold-commit: f07e25a209f4, timestamp: 2026-11-09T11:34:03+00:00

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import ClassVar

from mcp_configs import from_environment
from mcp_configs import shared_config
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

from polixis_mcp.persistence.store import open_store
from polixis_mcp.persistence.store import Store
from polixis_mcp.persistence.store import StoreSettings


class ResponseCacheSettings(BaseSettings):
    """How long Polixis's answers are reused to answer the same request again, which spares the
    API key's quota. They are licensed data about real people, which Polixis updates in real time,
    so the time is capped at an hour. A changed `key_prefix` leaves every answer cached under the
    old one unread, until it expires and the cull deletes it.
    """

    model_config: ClassVar[SettingsConfigDict] = shared_config("RESPONSE_CACHE_")

    enabled: bool = True
    ttl_seconds: int = Field(default=15 * 60, ge=1, le=60 * 60)
    key_prefix: str = Field(default="v1", pattern=r"^[A-Za-z0-9._-]{1,40}$")


class PersistenceSettings(BaseModel):
    """Each store reads its own settings from the environment."""

    store: StoreSettings = Field(default_factory=lambda: from_environment(StoreSettings))
    response_cache: ResponseCacheSettings = Field(default_factory=ResponseCacheSettings)


class Persistence(BaseModel):
    """What the contexts receive: every store the MCP owns, opened once by the server lifespan."""

    model_config: ClassVar[ConfigDict] = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    store: Store
    response_cache: ResponseCacheSettings


@asynccontextmanager
async def open_persistence(settings: PersistenceSettings) -> AsyncGenerator[Persistence]:
    async with (
        open_store(settings.store) as store,
    ):
        yield Persistence(store=store, response_cache=settings.response_cache)
