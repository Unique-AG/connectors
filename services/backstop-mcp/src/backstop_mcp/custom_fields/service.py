from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backstop_mcp.backstop_client.client import BackstopClient
from backstop_mcp.config import CustomFieldOverrideConfig
from backstop_mcp.custom_fields.fetch import (
    definitions_from_overrides_only,
    fetch_custom_field_definitions,
)
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
    """Process-wide custom-field schema cache + resolution."""

    session_factory: async_sessionmaker[AsyncSession]
    base_url: str
    overrides: dict[str, CustomFieldOverrideConfig]
    _index: dict[str, list[CustomFieldDefinition]]
    _lock: asyncio.Lock
    _loaded_from_db: bool
    _has_crm_snapshot: bool

    def glossary_for(self, entity_type: str) -> str:
        entity = normalize_entity_type(entity_type)
        return format_glossary(self._index.get(entity, []), entity_type=entity)

    def definitions_for(self, entity_type: str) -> list[CustomFieldDefinition]:
        return list(self._index.get(normalize_entity_type(entity_type), []))

    async def ensure_loaded(self, client: BackstopClient | None = None) -> None:
        """Load DB snapshot (or overrides-only); fetch from CRM if missing and client given."""
        async with self._lock:
            if not self._loaded_from_db:
                await self._load_from_db_unlocked()
            if self._has_crm_snapshot or client is None:
                return
            await self._refresh_unlocked(client)

    async def refresh(self, client: BackstopClient) -> list[CustomFieldDefinition]:
        async with self._lock:
            return await self._refresh_unlocked(client)

    async def resolve(
        self,
        *,
        entity_type: str,
        query: str,
        client: BackstopClient | None = None,
        refresh: bool = False,
    ) -> FieldResolveResult:
        if refresh:
            assert client is not None, "refresh=True requires a BackstopClient"
            await self.refresh(client)
        else:
            await self.ensure_loaded(client)
        return resolve_in_index(self._index, entity_type=entity_type, query=query)

    async def _load_from_db_unlocked(self) -> None:
        async with get_session(self.session_factory) as session:
            snapshot = await load_snapshot(session, self.base_url)
        if snapshot is not None:
            self._set_definitions(snapshot)
            self._has_crm_snapshot = True
        else:
            self._set_definitions(definitions_from_overrides_only(self.overrides))
            self._has_crm_snapshot = False
        self._loaded_from_db = True

    async def _refresh_unlocked(self, client: BackstopClient) -> list[CustomFieldDefinition]:
        definitions = await fetch_custom_field_definitions(client, self.overrides)
        async with get_session(self.session_factory) as session:
            await save_snapshot(session, self.base_url, definitions)
        self._set_definitions(definitions)
        self._has_crm_snapshot = True
        self._loaded_from_db = True
        return definitions

    def _set_definitions(self, definitions: list[CustomFieldDefinition]) -> None:
        self._index = build_index(definitions)


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
) -> CustomFieldsService:
    return CustomFieldsService(
        session_factory=session_factory,
        base_url=base_url.rstrip("/"),
        overrides=overrides,
        _index={},
        _lock=asyncio.Lock(),
        _loaded_from_db=False,
        _has_crm_snapshot=False,
    )


def reset_custom_fields_service_for_tests() -> None:
    global _service
    _service = None
