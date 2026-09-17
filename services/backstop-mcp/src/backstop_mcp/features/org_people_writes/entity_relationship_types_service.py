import logging
from datetime import timedelta
from typing import Self

from fastmcp.exceptions import ToolError

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.caching import CachedValue
from backstop_mcp.features.data_hygiene import (
    EmploymentRulesDto,
    EntityRelationshipRef,
    RelationshipTypeAttributes,
)
from backstop_mcp.features.org_people_writes.responses import EntityRelationshipTypeResponse
from backstop_mcp.timed_gate import TimedGate

logger = logging.getLogger(__name__)

# How long a failed fetch is remembered before Backstop is tried again. Long enough that a burst
# of tool calls against a down instance costs one round-trip rather than one each, short enough
# that a recovered instance is picked up without an operator waiting on the TTL.
_FAILURE_COOLDOWN = timedelta(seconds=30)


class EntityRelationshipTypesService:
    """Process-wide entity-relationship-type vocabulary, refetched when the TTL lapses.

    Employment writes send a per-tenant type id from this catalog; a failed fetch propagates.
    """

    def __init__(
        self, *, client: BackstopClient, ttl: timedelta, rules: EmploymentRulesDto
    ) -> None:
        self._client: BackstopClient = client
        self._rules: EmploymentRulesDto = rules
        self._cache: CachedValue[dict[str, EntityRelationshipTypeResponse]] = CachedValue(
            ttl=ttl,
            snapshot=dict,
            name="entity-relationship-type",
            log_prefix="org_people_writes.entity_relationship_types",
            serve_stale=False,
        )
        self._cooldown: TimedGate = TimedGate(duration=_FAILURE_COOLDOWN)
        self._failure: Exception | None = None

    @classmethod
    def with_ttl_minutes(
        cls, *, client: BackstopClient, ttl_minutes: int, rules: EmploymentRulesDto
    ) -> Self:
        return cls(client=client, ttl=timedelta(minutes=ttl_minutes), rules=rules)

    async def get_employment_type(self) -> EntityRelationshipTypeResponse:
        """The unique current-employment type from this instance's catalog.

        Configured ids win when set; otherwise name markers select. Former types are always
        excluded. No match, or more than one, is a `ToolError` — never a guess.
        """
        catalog = await self.get_catalog()
        matches = [row for row in catalog.values() if self._is_current_employment(row)]
        available = self._available_type_names(catalog)
        if not matches:
            raise ToolError(
                "No employment entity-relationship type matched the configured vocabulary. "
                + f"Available types: {available}."
            )
        if len(matches) > 1:
            labels = self._match_labels(matches)
            raise ToolError(
                f"Employment entity-relationship type is ambiguous: {labels}. "
                + f"Available types: {available}."
            )
        return matches[0]

    async def get_catalog(self) -> dict[str, EntityRelationshipTypeResponse]:
        failure = self._failure
        if failure is not None and self._cooldown.within():
            raise failure

        try:
            catalog, _status = await self._cache.get(self._fetch_types)
        except Exception as error:
            self._failure = error
            self._cooldown.mark()
            logger.warning(
                "org_people_writes.entity_relationship_types.fetch_failed", exc_info=True
            )
            raise

        self._failure = None
        self._cooldown.clear()
        return catalog

    def _is_current_employment(self, row: EntityRelationshipTypeResponse) -> bool:
        if self._rules.former.matches(type_id=row.id, type_name=row.name):
            return False
        employment = self._rules.employment
        if employment.type_ids:
            return row.id in employment.type_ids
        return employment.matches(type_id=row.id, type_name=row.name)

    async def _fetch_types(self) -> dict[str, EntityRelationshipTypeResponse]:
        page = await self._client.paginate(
            f"/{EntityRelationshipRef.TYPES_RESOURCE}",
            schema=BackstopApiResource[RelationshipTypeAttributes],
            max_records=None,
            page_size=100,
        )
        types: dict[str, EntityRelationshipTypeResponse] = {}
        for resource in page.items:
            name = resource.attributes.name
            if name is None:
                continue
            types[resource.id] = EntityRelationshipTypeResponse(id=resource.id, name=name)
        return types

    def _available_type_names(self, catalog: dict[str, EntityRelationshipTypeResponse]) -> str:
        return ", ".join(sorted(row.name for row in catalog.values()))

    def _match_labels(self, matches: list[EntityRelationshipTypeResponse]) -> str:
        return ", ".join(
            f"{row.name} ({row.id})" for row in sorted(matches, key=lambda row: (row.name, row.id))
        )
