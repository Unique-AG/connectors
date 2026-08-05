import asyncio
from datetime import UTC, datetime, timedelta

from fastmcp import Context
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backstop_mcp.backstop_client.client import BackstopClient
from backstop_mcp.config import CustomFieldOverrideConfig
from backstop_mcp.custom_fields.entity_types import normalize_entity_type
from backstop_mcp.custom_fields.fetch import fetch_custom_field_definitions
from backstop_mcp.custom_fields.glossary import format_glossary
from backstop_mcp.custom_fields.index import (
    DefinitionIndex,
    FieldResolution,
    build_index,
    resolve_in_index,
)
from backstop_mcp.custom_fields.store import load_snapshot, save_snapshot
from backstop_mcp.custom_fields.types import CustomFieldDefinition
from backstop_mcp.db.engine import read_session, transaction
from backstop_mcp.logging import get_logger
from backstop_mcp.metrics import CUSTOM_FIELD_SCHEMA_LOADS
from backstop_mcp.resolution import Ambiguous, elicit_choice

logger = get_logger(__name__)


class CustomFieldsService:
    """Process-wide custom-field schema cache + resolution.

    Definitions only ever come from a real Backstop fetch, persisted as a snapshot keyed by
    `base_url` (so one instance's schema is shared across every user of it). `overrides` are
    a display overlay applied to fetched fields — never a source of fields on their own, so
    until a fetch succeeds this service serves nothing and the glossary stays absent.

    Constructed by `create_app()` and reached via `runtime.get_services().custom_fields`.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        base_url: str,
        overrides: dict[str, CustomFieldOverrideConfig],
        ttl: timedelta,
    ) -> None:
        self.session_factory: async_sessionmaker[AsyncSession] = session_factory
        self.base_url: str = base_url.rstrip("/")
        self.overrides: dict[str, CustomFieldOverrideConfig] = overrides
        self.ttl: timedelta = ttl
        self._index: DefinitionIndex = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        self._fetched_at: datetime | None = None

    @property
    def is_fresh(self) -> bool:
        """Whether the in-memory schema came from a fetch recent enough to trust.

        False both when nothing has ever been fetched and when the snapshot has aged past
        `ttl`. Lets callers decide whether it's worth acquiring a client — which costs a DB
        read plus a credential decrypt — before asking for a refresh.
        """
        return self._fetched_at is not None and datetime.now(UTC) - self._fetched_at < self.ttl

    @property
    def has_definitions(self) -> bool:
        """Whether anything is loaded at all, fresh or stale."""
        return bool(self._index)

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
        """Bring the schema within `ttl`, tolerating a failed refresh when a copy exists.

        A stale schema is far more useful than none: definitions change when an admin adds a
        field, so a copy from last week almost certainly still resolves the caller's query.
        Letting a Backstop hiccup propagate here would fail every field lookup outright, so a
        refresh failure is logged and the existing index kept. `refresh()` is the loud path.
        """
        async with self._lock:
            if self.is_fresh:
                return
            # Another replica may have refreshed since this process last looked; a primary-key
            # lookup is far cheaper than re-paginating the whole schema.
            await self._load_from_db_unlocked()
            if self.is_fresh:
                return
            try:
                await self._refresh_unlocked(client)
            except Exception:
                if not self.has_definitions:
                    raise
                logger.warning(
                    "custom_fields.schema.refresh_failed_serving_stale",
                    fetched_at=self._fetched_at.isoformat() if self._fetched_at else None,
                    exc_info=True,
                )
                CUSTOM_FIELD_SCHEMA_LOADS.add(1, {"source": "stale"})

    async def refresh(self, client: BackstopClient) -> list[CustomFieldDefinition]:
        """Fetch from Backstop unconditionally, ignoring `ttl`. Raises on failure."""
        async with self._lock:
            return await self._refresh_unlocked(client)

    async def resolve(
        self,
        *,
        entity_type: str,
        query: str,
        client: BackstopClient,
        refresh: bool = False,
        ctx: Context | None = None,
    ) -> FieldResolution:
        """Resolve one field by name, applying the shared ambiguity policy.

        When `ctx` is supplied and several fields match, the user is asked to pick one — the
        same policy party resolution uses (see `resolution.py`). Without a `ctx` the ambiguity
        is returned for the caller to surface.
        """
        if refresh:
            await self.refresh(client)
        else:
            await self.ensure_fresh(client)

        result = resolve_in_index(self._index, entity_type=entity_type, query=query)
        if ctx is not None and isinstance(result, Ambiguous):
            return await elicit_choice(
                ctx,
                result,
                prompt=(
                    f'Several {result.scope} fields matched "{result.query}". '
                    + "Which one did you mean?"
                ),
            )
        return result

    async def _load_from_db_unlocked(self) -> None:
        async with read_session(self.session_factory) as session:
            snapshot = await load_snapshot(session, self.base_url)
        if snapshot is None:
            # Keep whatever is already in memory: an absent or unreadable row is not evidence
            # that this process's own definitions are wrong.
            return
        self._index = build_index(snapshot.definitions)
        self._fetched_at = snapshot.fetched_at
        CUSTOM_FIELD_SCHEMA_LOADS.add(1, {"source": "snapshot"})

    async def _refresh_unlocked(self, client: BackstopClient) -> list[CustomFieldDefinition]:
        definitions = await fetch_custom_field_definitions(client, self.overrides)
        fetched_at = datetime.now(UTC)
        async with transaction(self.session_factory) as session:
            await save_snapshot(session, self.base_url, definitions, fetched_at)
        self._index = build_index(definitions)
        self._fetched_at = fetched_at
        CUSTOM_FIELD_SCHEMA_LOADS.add(1, {"source": "backstop"})
        logger.info("custom_fields.schema.refreshed", definitions=len(definitions))
        return definitions


def create_custom_fields_service(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    base_url: str,
    overrides: dict[str, CustomFieldOverrideConfig],
    ttl_minutes: int,
) -> CustomFieldsService:
    return CustomFieldsService(
        session_factory=session_factory,
        base_url=base_url,
        overrides=overrides,
        ttl=timedelta(minutes=ttl_minutes),
    )
