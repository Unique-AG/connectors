import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import ClassVar

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.auth import current_subject
from backstop_mcp.features.custom_fields.entity_types import normalize_entity_type
from backstop_mcp.features.custom_fields.fetch import fetch_custom_field_definitions
from backstop_mcp.features.custom_fields.index import DefinitionIndex, build_index
from backstop_mcp.features.custom_fields.types import CustomFieldDefinition
from backstop_mcp.metrics import CUSTOM_FIELD_SCHEMA_LOADS
from backstop_mcp.timed_gate import TimedGate

logger = logging.getLogger(__name__)


@dataclass
class _SubjectSchema:
    """In-memory schema state for one subject."""

    index: DefinitionIndex = field(default_factory=dict)
    freshness: TimedGate = field(default_factory=lambda: TimedGate(duration=timedelta(0)))
    refresh_floor: TimedGate = field(default_factory=lambda: TimedGate(duration=timedelta(0)))


class CustomFieldsService:
    """Per-caller custom-field schema cache.

    Definitions only ever come from a real Backstop fetch, held in memory per subject so one
    caller's refresh cannot populate another's catalog.
    Until a fetch succeeds this service serves nothing.

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

    def __init__(self, *, ttl: timedelta) -> None:
        self._ttl: timedelta = ttl
        self._by_subject: dict[str, _SubjectSchema] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    def _resolve_subject(self, subject: str | None) -> str | None:
        return subject if subject is not None else current_subject()

    def _entry(self, subject: str) -> _SubjectSchema:
        entry = self._by_subject.get(subject)
        if entry is not None:
            return entry
        entry = _SubjectSchema(
            freshness=TimedGate(duration=self._ttl),
            refresh_floor=TimedGate(duration=self.MIN_REFRESH_INTERVAL),
        )
        self._by_subject[subject] = entry
        return entry

    def is_fresh(self, subject: str | None = None) -> bool:
        """Whether this subject's in-memory schema came from a fetch recent enough to trust."""
        resolved = self._resolve_subject(subject)
        if resolved is None:
            return False
        entry = self._by_subject.get(resolved)
        return entry is not None and entry.freshness.within()

    def has_definitions(self, subject: str | None = None) -> bool:
        """Whether this subject's in-memory schema has any definitions loaded."""
        resolved = self._resolve_subject(subject)
        if resolved is None:
            return False
        entry = self._by_subject.get(resolved)
        return entry is not None and bool(entry.index)

    def index_for(self, subject: str | None = None) -> DefinitionIndex:
        """The in-memory schema index for one subject. Empty when unknown / unauthenticated."""
        resolved = self._resolve_subject(subject)
        if resolved is None:
            return {}
        entry = self._by_subject.get(resolved)
        return entry.index if entry is not None else {}

    def definitions_for(
        self, entity_type: str, *, subject: str | None = None
    ) -> list[CustomFieldDefinition]:
        resolved = self._resolve_subject(subject)
        if resolved is None:
            return []
        entry = self._by_subject.get(resolved)
        if entry is None:
            return []
        entity = normalize_entity_type(entity_type)
        if entity is None:
            return []
        return list(entry.index.get(entity, []))

    async def ensure_fresh(self, client: BackstopClient, *, subject: str | None = None) -> None:
        """Bring this subject's schema within `ttl`, tolerating a failed refresh when a copy exists.

        A stale schema is far more useful than none: definitions change when an admin adds a
        field, so a copy from last week almost certainly still resolves the caller's query.
        Letting a Backstop hiccup propagate here would fail every field lookup outright, so a
        refresh failure is logged and the existing index kept. `refresh()` is the loud path.

        The refresh floor applies here too, and this is the path that needs it most: a failed
        refresh leaves `is_fresh` false, so without the floor every subsequent call — every
        `tools/list`, every resolution — would attempt the fetch again and hammer a Backstop
        that is already struggling.
        """
        resolved = self._resolve_subject(subject)
        if resolved is None:
            raise ValueError("custom-field schema ensure_fresh requires a subject")
        if self.is_fresh(resolved):
            return
        async with self._lock:
            if self.is_fresh(resolved):
                return
            if self._entry(resolved).refresh_floor.within():
                return
            try:
                await self._refresh_unlocked(client, resolved)
            except Exception:
                if not self.has_definitions(resolved):
                    raise
                entry = self._entry(resolved)
                logger.warning(
                    "custom_fields.schema.refresh_failed_serving_stale",
                    extra={
                        "subject": resolved,
                        "fetched_at": (
                            entry.freshness.marked_at.isoformat()
                            if entry.freshness.marked_at
                            else None
                        ),
                    },
                    exc_info=True,
                )
                CUSTOM_FIELD_SCHEMA_LOADS.add(1, {"source": "stale"})

    async def refresh(
        self, client: BackstopClient, *, subject: str | None = None
    ) -> list[CustomFieldDefinition]:
        """Fetch from Backstop, ignoring `ttl` but not `MIN_REFRESH_INTERVAL`. Raises on failure.

        The loud path: unlike `ensure_fresh` a failure propagates, because the caller explicitly
        asked for new data and serving them a stale answer as if it were fresh would be a lie.
        Inside the floor the fetch is skipped and the current definitions are returned — the
        caller still gets a coherent answer, just not a newer one.
        """
        resolved = self._resolve_subject(subject)
        if resolved is None:
            raise ValueError("custom-field schema refresh requires a subject")
        async with self._lock:
            entry = self._entry(resolved)
            if entry.refresh_floor.within():
                logger.info(
                    "custom_fields.schema.refresh_floored",
                    extra={
                        "subject": resolved,
                        "attempted_at": (
                            entry.refresh_floor.marked_at.isoformat()
                            if entry.refresh_floor.marked_at
                            else None
                        ),
                        "min_interval_seconds": self.MIN_REFRESH_INTERVAL.total_seconds(),
                    },
                )
                return self._all_definitions(entry)
            return await self._refresh_unlocked(client, resolved)

    def _all_definitions(self, entry: _SubjectSchema) -> list[CustomFieldDefinition]:
        return [definition for group in entry.index.values() for definition in group]

    async def _refresh_unlocked(
        self, client: BackstopClient, subject: str
    ) -> list[CustomFieldDefinition]:
        entry = self._entry(subject)
        # Stamped before the call, not after, so a fetch that fails or hangs still counts against
        # the floor — otherwise an unreachable Backstop would be retried on every request.
        entry.refresh_floor.mark()
        definitions = await fetch_custom_field_definitions(client)
        fetched_at = datetime.now(UTC)
        entry.index = build_index(definitions)
        entry.freshness.mark(fetched_at)
        CUSTOM_FIELD_SCHEMA_LOADS.add(1, {"source": "backstop"})
        logger.info(
            "custom_fields.schema.refreshed",
            extra={"subject": subject, "definitions": len(definitions)},
        )
        return definitions


def create_custom_fields_service(*, ttl_minutes: int) -> CustomFieldsService:
    return CustomFieldsService(ttl=timedelta(minutes=ttl_minutes))
