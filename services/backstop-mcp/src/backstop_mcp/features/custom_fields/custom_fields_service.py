import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Self, cast

from pydantic import ValidationError

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient, ResourceRef
from backstop_mcp.caching import CachedValue, CacheFreshness, CacheSource
from backstop_mcp.features.custom_fields.api_responses import (
    CustomFieldDefinitionAttributes,
    CustomFieldValueAttributes,
)
from backstop_mcp.features.custom_fields.internal_dto import (
    CustomFieldDefinitionDto,
    CustomFieldEntityReferenceDto,
    ResolvedCustomFieldValueDto,
)
from backstop_mcp.features.custom_fields.responses import ResolvedCustomFieldValueResponse
from backstop_mcp.features.entity_types import party_search_type
from backstop_mcp.metrics import CUSTOM_FIELD_SCHEMA_LOADS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CustomFieldFilters:
    tabs: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    group_ids: tuple[int, ...] = ()
    definition_ids: tuple[str, ...] = ()
    names: tuple[str, ...] = ()


_NO_FILTERS = CustomFieldFilters()


async def _fetch_custom_field_definitions(
    client: BackstopClient,
) -> dict[str, CustomFieldDefinitionDto]:
    """Fetch Backstop's full custom-field schema in one paginated walk, keyed by definition id."""
    page = await client.paginate(
        "/custom-field-definitions",
        schema=BackstopApiResource[CustomFieldDefinitionAttributes],
        max_records=None,
        page_size=1000,
    )

    definitions_by_id: dict[str, CustomFieldDefinitionDto] = {}
    for resource in page.items:
        definition = CustomFieldDefinitionDto.from_resource(resource)
        if definition is None:
            continue
        existing = definitions_by_id.get(definition.id)
        if existing is None:
            definitions_by_id[definition.id] = definition
        elif existing != definition:
            logger.warning(
                "Conflicting custom-field definitions for duplicate id %r; "
                + "retaining first definition",
                definition.id,
            )
    return definitions_by_id


def _record_schema_load(source: CacheSource) -> None:
    CUSTOM_FIELD_SCHEMA_LOADS.add(1, {"source": source})


class CustomFieldsService:
    """Process-wide custom-field schema catalog, and the join of record values onto it.

    A party GET only embeds `{definitionId, value}`. Names, types, tabs, groups and picklist
    options live on the definition catalog. Until a fetch succeeds this service has nothing to
    serve. Constructed by `get_custom_fields_service` in this feature's `dependencies.py`.

    The TTL, single-flight and serve-stale protocol behind `get` is the composed `CachedValue`;
    this is the one catalog that meters its loads, via `on_load`.
    """

    _ENTITY_FIELD_TYPE: str = "entity"
    _OPTION_TEXT_KEYS: tuple[str, ...] = ("label", "value", "name", "id")

    def __init__(
        self, *, client: BackstopClient, ttl: timedelta, caching_enabled: bool = True
    ) -> None:
        self._client: BackstopClient = client
        self._cache: CachedValue[dict[str, CustomFieldDefinitionDto]] = CachedValue(
            ttl=ttl,
            snapshot=dict,
            name="custom-field",
            log_prefix="custom_fields.schema",
            caching_enabled=caching_enabled,
            on_load=_record_schema_load,
        )

    @classmethod
    def with_ttl_minutes(
        cls, *, client: BackstopClient, ttl_minutes: int, caching_enabled: bool = True
    ) -> Self:
        return cls(
            client=client, ttl=timedelta(minutes=ttl_minutes), caching_enabled=caching_enabled
        )

    async def get(
        self, *, refresh: bool = False
    ) -> tuple[dict[str, CustomFieldDefinitionDto], CacheFreshness]:
        return await self._cache.get(
            lambda: _fetch_custom_field_definitions(self._client), refresh=refresh
        )

    async def load_catalog(self) -> dict[str, CustomFieldDefinitionDto] | None:
        """The definition catalog, or `None` when it could not be loaded.

        `None` is distinct from an empty catalog: the caller can tell "unavailable" from
        "no custom fields on this record". Overlap this with another GET so `join_values`
        hits a warm cache.
        """
        try:
            catalog, _status = await self.get()
        except Exception:
            logger.warning("custom_fields.values.catalog_unavailable", exc_info=True)
            return None
        return catalog

    async def is_catalog_available(self) -> bool:
        catalog = await self.load_catalog()
        return catalog is not None

    async def join_values(
        self,
        regular_custom_field_values: Sequence[CustomFieldValueAttributes] | None,
        *,
        filters: CustomFieldFilters = _NO_FILTERS,
    ) -> list[ResolvedCustomFieldValueResponse]:
        """Load the catalog (or reuse a warm cache) and join stored values onto it.

        Party and entity-specific definitions both appear on one record, so this uses the
        full catalog. ENTITY values become party references; picklist values that left the
        current option list are kept and flagged. A cold-cache fetch failure returns an
        empty list rather than raising, so the parent lookup still succeeds.
        """
        catalog = await self.load_catalog()
        if catalog is None:
            return []
        published: list[ResolvedCustomFieldValueResponse] = []
        for stored in regular_custom_field_values or ():
            resolved = self._with_catalog_definition(stored, catalog)
            if resolved is None:
                continue
            if not self._included_by_filters(resolved, filters):
                continue
            published.append(ResolvedCustomFieldValueResponse.from_dto(resolved))
        return published

    def _with_catalog_definition(
        self,
        stored: CustomFieldValueAttributes,
        catalog: Mapping[str, CustomFieldDefinitionDto],
    ) -> ResolvedCustomFieldValueDto | None:
        definition_id = stored.definition_id
        if not definition_id:
            return None
        definition = catalog.get(definition_id)
        if definition is None:
            logger.warning(
                "custom_fields.values.definition_missing",
                extra={
                    "definition_id": definition_id,
                    "remedy": "list_custom_fields(refresh=true)",
                },
            )
            return None
        return ResolvedCustomFieldValueDto.from_definition(
            definition,
            value=self._as_published_value(stored.value, definition.field_type),
            outside_current_options=self._not_in_current_options(
                stored.value, definition.select_options
            ),
        )

    def _as_published_value(self, value: object, field_type: str | None) -> object:
        if field_type is None or field_type.casefold() != self._ENTITY_FIELD_TYPE:
            return value
        try:
            ref = ResourceRef.model_validate(value)
        except ValidationError:
            return value
        resource_type = ref.resource_type
        return CustomFieldEntityReferenceDto(
            id=ref.resource_id,
            resource_type=resource_type,
            resource_link=ref.resource_link,
            search_type=party_search_type(resource_type) if resource_type else None,
        )

    def _not_in_current_options(self, value: object, select_options: Sequence[object]) -> bool:
        if not select_options or value is None:
            return False
        current = self._current_option_texts(select_options)
        stored: list[object] = (
            list(cast(list[object], value)) if isinstance(value, list) else [value]
        )
        for item in stored:
            text = self._option_text(item)
            if text is None or text not in current:
                return True
        return False

    def _current_option_texts(self, select_options: Sequence[object]) -> set[str]:
        current: set[str] = set()
        for option in select_options:
            if isinstance(option, str):
                current.add(option)
                continue
            if isinstance(option, Mapping):
                payload = cast(Mapping[str, object], option)
                for key in self._OPTION_TEXT_KEYS:
                    text = self._option_text(payload.get(key))
                    if text is not None:
                        current.add(text)
        return current

    def _option_text(self, value: object) -> str | None:
        if isinstance(value, str):
            return value
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, int):
            return str(value)
        return None

    def _included_by_filters(
        self, resolved: ResolvedCustomFieldValueDto, filters: CustomFieldFilters
    ) -> bool:
        if filters.tabs and not self._equals_ignore_case(resolved.tab_name, filters.tabs):
            return False
        if filters.groups and not self._equals_ignore_case(resolved.group_name, filters.groups):
            return False
        if filters.group_ids and resolved.group_id not in set(filters.group_ids):
            return False
        if filters.definition_ids and resolved.definition_id not in {
            entry.strip() for entry in filters.definition_ids
        }:
            return False
        return not filters.names or self._equals_ignore_case(resolved.name, filters.names)

    def _equals_ignore_case(self, actual: str | None, wanted: Sequence[str]) -> bool:
        if actual is None:
            return False
        folded = actual.casefold()
        return any(entry.casefold() == folded for entry in wanted)
