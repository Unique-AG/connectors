from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backstop_mcp.backstop_client.client import BackstopClient
from backstop_mcp.config import CustomFieldOverrideConfig
from backstop_mcp.custom_fields.fetch import fetch_custom_field_definitions
from backstop_mcp.custom_fields.glossary import format_glossary
from backstop_mcp.custom_fields.index import build_index, resolve_in_index
from backstop_mcp.custom_fields.overrides import normalize_entity_type
from backstop_mcp.custom_fields.store import load_snapshot, save_snapshot
from backstop_mcp.custom_fields.types import (
    CustomFieldDefinition,
    FieldResolveResult,
)
from backstop_mcp.db.engine import get_session


@dataclass
class CustomFieldsService:
    """Process-wide custom-field schema cache + resolution.

    Definitions only ever come from a real Backstop fetch, persisted as a snapshot keyed by
    `base_url` (so one instance's schema is shared across every user of it). `overrides` are
    a display overlay applied to fetched fields — never a source of fields on their own, so
    until a fetch succeeds this service serves nothing and the glossary stays absent.

    Two entry points, split by what they need rather than by what they were handed:
    `load_cached()` reads the snapshot and requires no credential; `ensure_fresh(client)` and
    `refresh(client)` contact Backstop and therefore require one.
    """

    session_factory: async_sessionmaker[AsyncSession]
    base_url: str
    overrides: dict[str, CustomFieldOverrideConfig]
    ttl: timedelta
    _index: dict[str, list[CustomFieldDefinition]]
    _lock: asyncio.Lock
    _fetched_at: datetime | None

    @property
    def is_fresh(self) -> bool:
        """Whether the in-memory schema came from a fetch recent enough to trust.

        False both when nothing has ever been fetched and when the snapshot has aged past
        `ttl`. Lets callers decide whether it's worth acquiring a client — which costs a DB
        read plus a credential decrypt — before asking for a refresh.
        """
        return self._fetched_at is not None and datetime.now(UTC) - self._fetched_at < self.ttl

    def glossary_for(self, entity_type: str) -> str:
        entity = normalize_entity_type(entity_type)
        return format_glossary(self._index.get(entity, []), entity_type=entity)

    def definitions_for(self, entity_type: str) -> list[CustomFieldDefinition]:
        return list(self._index.get(normalize_entity_type(entity_type), []))

    async def load_cached(self) -> None:
        """Populate the index from the persisted snapshot. Never contacts Backstop.

        Safe for callers with no credential (e.g. enriching a tool listing). Re-reads the row
        whenever the in-memory copy isn't fresh, so a replica picks up a sibling's refresh
        instead of trusting its own aged copy; once fresh it's a pure memory read.
        """
        async with self._lock:
            if not self.is_fresh:
                await self._load_from_db_unlocked()

    async def ensure_fresh(self, client: BackstopClient) -> None:
        """Fetch from Backstop unless the snapshot — in memory or in the DB — is within `ttl`."""
        async with self._lock:
            if self.is_fresh:
                return
            # Another replica may have refreshed since this process last looked; a primary-key
            # lookup is far cheaper than re-paginating the whole schema.
            await self._load_from_db_unlocked()
            if self.is_fresh:
                return
            await self._refresh_unlocked(client)

    async def refresh(self, client: BackstopClient) -> list[CustomFieldDefinition]:
        """Fetch from Backstop unconditionally, ignoring `ttl`."""
        async with self._lock:
            return await self._refresh_unlocked(client)

    async def resolve(
        self,
        *,
        entity_type: str,
        query: str,
        client: BackstopClient,
        refresh: bool = False,
    ) -> FieldResolveResult:
        if refresh:
            await self.refresh(client)
        else:
            await self.ensure_fresh(client)
        return resolve_in_index(self._index, entity_type=entity_type, query=query)

    async def _load_from_db_unlocked(self) -> None:
        async with get_session(self.session_factory) as session:
            snapshot = await load_snapshot(session, self.base_url)
        self._index = build_index(snapshot.definitions if snapshot is not None else [])
        self._fetched_at = snapshot.fetched_at if snapshot is not None else None

    async def _refresh_unlocked(self, client: BackstopClient) -> list[CustomFieldDefinition]:
        definitions = await fetch_custom_field_definitions(client, self.overrides)
        fetched_at = datetime.now(UTC)
        async with get_session(self.session_factory) as session:
            await save_snapshot(session, self.base_url, definitions, fetched_at)
        self._index = build_index(definitions)
        self._fetched_at = fetched_at
        return definitions


_service: CustomFieldsService | None = None


def configure_custom_fields_service(service: CustomFieldsService) -> None:
    global _service
    _service = service


def get_custom_fields_service() -> CustomFieldsService:
    assert _service is not None, (
        "configure_custom_fields_service() must be called during app startup"
    )
    return _service


def create_custom_fields_service(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    base_url: str,
    overrides: dict[str, CustomFieldOverrideConfig],
    ttl_minutes: int,
) -> CustomFieldsService:
    return CustomFieldsService(
        session_factory=session_factory,
        base_url=base_url.rstrip("/"),
        overrides=overrides,
        ttl=timedelta(minutes=ttl_minutes),
        _index={},
        _lock=asyncio.Lock(),
        _fetched_at=None,
    )


def reset_custom_fields_service_for_tests() -> None:
    global _service
    _service = None
