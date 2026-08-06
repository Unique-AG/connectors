import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.db import read_session, transaction
from backstop_mcp.features.custom_fields.entity_types import normalize_entity_type
from backstop_mcp.features.custom_fields.fetch import fetch_custom_field_definitions
from backstop_mcp.features.custom_fields.glossary import format_glossary
from backstop_mcp.features.custom_fields.index import DefinitionIndex, build_index
from backstop_mcp.features.custom_fields.overrides import FieldOverride
from backstop_mcp.features.custom_fields.store import load_snapshot, save_snapshot
from backstop_mcp.features.custom_fields.types import CustomFieldDefinition
from backstop_mcp.metrics import CUSTOM_FIELD_SCHEMA_LOADS

logger = logging.getLogger(__name__)


class CustomFieldsService:
    """Process-wide custom-field schema cache.

    Definitions only ever come from a real Backstop fetch, persisted as a snapshot keyed by
    `base_url` (so one instance's schema is shared across every user of it). `overrides` are
    a display overlay applied to fetched fields — never a source of fields on their own, so
    until a fetch succeeds this service serves nothing and the glossary stays absent.

    Name → definition resolution (including elicitation) lives in `resolve.py`, mirroring
    `party_resolver.resolve`. Constructed by `create_app()` and reached via
    `runtime.get_services().custom_fields`.
    """

    # Floor on how often an upstream fetch can be attempted, whatever the caller asked for.
    # `list_custom_fields` exposes `refresh` to the model, and one refresh is two uncapped
    # paginations taken under the lock every other caller's cold path waits on — so without a
    # floor a model that habitually passes `refresh=true` serializes every concurrent caller
    # behind repeated full re-fetches and spends the user's Backstop concurrency budget on a
    # schema that changes when an admin adds a field. Well below `ttl`, so it only ever bounds
    # forced refreshes, never the ordinary TTL-driven one.
    MIN_REFRESH_INTERVAL: ClassVar[timedelta] = timedelta(minutes=1)

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        base_url: str,
        overrides: dict[str, FieldOverride],
        ttl: timedelta,
    ) -> None:
        self._session_factory: async_sessionmaker[AsyncSession] = session_factory
        self._base_url: str = base_url.rstrip("/")
        self._overrides: dict[str, FieldOverride] = overrides
        self._ttl: timedelta = ttl
        self._index: DefinitionIndex = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        self._fetched_at: datetime | None = None
        # When an upstream fetch was last *attempted*, as opposed to when the index was last
        # successfully filled (`_fetched_at`, which a snapshot read also sets). Tracked
        # separately so a failing Backstop can't be hammered either.
        self._refresh_attempted_at: datetime | None = None

    @property
    def is_fresh(self) -> bool:
        """Whether the in-memory schema came from a fetch recent enough to trust.

        False both when nothing has ever been fetched and when the snapshot has aged past
        `ttl`. Lets callers decide whether it's worth acquiring a client — which costs a DB
        read plus a credential decrypt — before asking for a refresh.
        """
        return self._fetched_at is not None and datetime.now(UTC) - self._fetched_at < self._ttl

    @property
    def has_definitions(self) -> bool:
        """Whether anything is loaded at all, fresh or stale."""
        return bool(self._index)

    @property
    def index(self) -> DefinitionIndex:
        """The in-memory schema index. Read-only for resolvers; mutated only by this service."""
        return self._index

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
        # Checked before acquiring, not inside: the lock is also held across `_refresh_unlocked`'s
        # two full paginations, so taking it merely to read `is_fresh` would park every warm
        # `tools/list` behind whichever caller happens to be doing a cold refresh. `is_fresh`
        # reads two attributes and can't tear, and a false negative here costs one extra
        # primary-key lookup after the re-check below — never a wrong answer.
        if self.is_fresh:
            return
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
        # Same pre-check as `load_cached`, for the same reason. The authoritative check is the
        # one inside the lock: it's what collapses a thundering herd of cold callers into one
        # fetch, since everyone queued behind the winner finds the schema already fresh.
        if self.is_fresh:
            return
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
                    extra={
                        "fetched_at": (self._fetched_at.isoformat() if self._fetched_at else None),
                    },
                    exc_info=True,
                )
                CUSTOM_FIELD_SCHEMA_LOADS.add(1, {"source": "stale"})

    async def refresh(self, client: BackstopClient) -> list[CustomFieldDefinition]:
        """Fetch from Backstop, ignoring `ttl` but not `MIN_REFRESH_INTERVAL`. Raises on failure.

        The loud path: unlike `ensure_fresh` a failure propagates, because the caller explicitly
        asked for new data and serving them a stale answer as if it were fresh would be a lie.
        Inside the floor the fetch is skipped and the current definitions are returned — the
        caller still gets a coherent answer, just not a newer one.
        """
        async with self._lock:
            if self._within_refresh_floor():
                logger.info(
                    "custom_fields.schema.refresh_floored",
                    extra={
                        "attempted_at": (
                            self._refresh_attempted_at.isoformat()
                            if self._refresh_attempted_at
                            else None
                        ),
                        "min_interval_seconds": self.MIN_REFRESH_INTERVAL.total_seconds(),
                    },
                )
                return self._all_definitions()
            return await self._refresh_unlocked(client)

    def _within_refresh_floor(self) -> bool:
        if self._refresh_attempted_at is None:
            return False
        return datetime.now(UTC) - self._refresh_attempted_at < self.MIN_REFRESH_INTERVAL

    def _all_definitions(self) -> list[CustomFieldDefinition]:
        return [definition for group in self._index.values() for definition in group]

    async def _load_from_db_unlocked(self) -> None:
        async with read_session(self._session_factory) as session:
            snapshot = await load_snapshot(session, self._base_url)
        if snapshot is None:
            # Keep whatever is already in memory: an absent or unreadable row is not evidence
            # that this process's own definitions are wrong.
            return
        self._index = build_index(snapshot.definitions)
        self._fetched_at = snapshot.fetched_at
        CUSTOM_FIELD_SCHEMA_LOADS.add(1, {"source": "snapshot"})

    async def _refresh_unlocked(self, client: BackstopClient) -> list[CustomFieldDefinition]:
        # Stamped before the call, not after, so a fetch that fails or hangs still counts against
        # the floor — otherwise an unreachable Backstop would be retried on every request.
        self._refresh_attempted_at = datetime.now(UTC)
        definitions = await fetch_custom_field_definitions(client, self._overrides)
        fetched_at = datetime.now(UTC)
        async with transaction(self._session_factory) as session:
            await save_snapshot(session, self._base_url, definitions, fetched_at)
        self._index = build_index(definitions)
        self._fetched_at = fetched_at
        CUSTOM_FIELD_SCHEMA_LOADS.add(1, {"source": "backstop"})
        logger.info(
            "custom_fields.schema.refreshed",
            extra={"definitions": len(definitions)},
        )
        return definitions


def create_custom_fields_service(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    base_url: str,
    overrides: dict[str, FieldOverride],
    ttl_minutes: int,
) -> CustomFieldsService:
    return CustomFieldsService(
        session_factory=session_factory,
        base_url=base_url,
        overrides=overrides,
        ttl=timedelta(minutes=ttl_minutes),
    )
