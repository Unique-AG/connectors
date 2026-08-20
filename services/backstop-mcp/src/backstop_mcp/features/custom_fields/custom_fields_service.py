import asyncio
import logging
from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Literal, Self, cast

from pydantic import ValidationError

from backstop_mcp.backstop_client import BackstopClient, ResourceRef
from backstop_mcp.features.custom_fields.api_responses import CustomFieldValueAttributes
from backstop_mcp.features.custom_fields.fetch_custom_field_definitions import (
    fetch_custom_field_definitions,
)
from backstop_mcp.features.custom_fields.internal_dto import (
    CustomFieldDefinitionDto,
    CustomFieldEntityReferenceDto,
    ResolvedCustomFieldValueDto,
)
from backstop_mcp.features.custom_fields.responses import ResolvedCustomFieldValueResponse
from backstop_mcp.features.entity_types import party_search_type
from backstop_mcp.metrics import CUSTOM_FIELD_SCHEMA_LOADS
from backstop_mcp.timed_gate import TimedGate

logger = logging.getLogger(__name__)

type CatalogResult = tuple[dict[str, CustomFieldDefinitionDto], Literal["ok", "stale"]]


class CustomFieldsService:
    """Process-wide custom-field schema catalog, and the join of record values onto it.

    A party GET only embeds `{definitionId, value}`. Names, types, tabs, groups and picklist
    options live on the definition catalog. Until a fetch succeeds this service has nothing to
    serve. Constructed by `get_custom_fields_service` in this feature's `dependencies.py`.
    """

    _STORED_VALUE_KEYS: frozenset[str] = frozenset(
        {"regularCustomFieldValues", "regular_custom_field_values"}
    )
    _ENTITY_FIELD_TYPE: str = "entity"
    _OPTION_TEXT_KEYS: tuple[str, ...] = ("label", "value", "name", "id")

    def __init__(self, *, ttl: timedelta) -> None:
        self._definitions: dict[str, CustomFieldDefinitionDto] | None = None
        self._freshness: TimedGate = TimedGate(duration=ttl)
        self._lock: asyncio.Lock = asyncio.Lock()
        self._in_flight: asyncio.Future[CatalogResult] | None = None

    @classmethod
    def with_ttl_minutes(cls, *, ttl_minutes: int) -> Self:
        return cls(ttl=timedelta(minutes=ttl_minutes))

    async def get(
        self, client: BackstopClient, *, refresh: bool = False
    ) -> tuple[dict[str, CustomFieldDefinitionDto], Literal["ok", "stale"]]:
        cached = self._definitions
        if cached is not None and self._freshness.within() and not refresh:
            return dict(cached), "ok"

        async with self._lock:
            cached = self._definitions
            if cached is not None and self._freshness.within() and not refresh:
                return dict(cached), "ok"
            if self._in_flight is not None and not self._in_flight.done():
                in_flight = self._in_flight
                owner = False
            else:
                in_flight = asyncio.get_running_loop().create_future()
                self._in_flight = in_flight
                owner = True

        if not owner:
            definitions, status = await in_flight
            return dict(definitions), status

        try:
            return await self._fetch(client, in_flight)
        except BaseException as error:
            if not in_flight.done():
                # Don't stamp CancelledError onto the shared future — waiters would then
                # look cancelled themselves. A regular exception lets them fail and retry.
                waiter_error: BaseException = error
                if isinstance(error, asyncio.CancelledError):
                    waiter_error = RuntimeError("custom-field catalog fetch was cancelled")
                in_flight.set_exception(waiter_error)
            raise
        finally:
            # Shield so a CancelledError cannot skip unpinning and leave later
            # get()s joining a finished future until process restart.
            await asyncio.shield(self._unpin_in_flight(in_flight))

    def take_stored_values(
        self, attributes: Mapping[str, object]
    ) -> tuple[dict[str, object], object]:
        """Pull Backstop's `regularCustomFieldValues` dump off a party record.

        Returns the record without that key, and the dump (or None). The dump is
        `{definitionId, value}` rows — names and types come from `resolve_values`.
        """
        stored: object = None
        record: dict[str, object] = {}
        for key, value in attributes.items():
            if key in self._STORED_VALUE_KEYS:
                if stored is None:
                    stored = value
                continue
            record[key] = value
        return record, stored

    async def resolve_values(
        self,
        client: BackstopClient,
        stored_values: object,
        *,
        tabs: Sequence[str] = (),
        groups: Sequence[str] = (),
        group_ids: Sequence[int] = (),
        definition_ids: Sequence[str] = (),
        names: Sequence[str] = (),
    ) -> list[ResolvedCustomFieldValueResponse]:
        """Look up each stored `{definitionId, value}` in the catalog.

        Party and entity-specific definitions both appear on one record, so this uses the
        full catalog. ENTITY values become party references; picklist values that left the
        current option list are kept and flagged. A cold-cache fetch failure returns an empty
        list rather than raising, so the party lookup still succeeds.
        """
        try:
            catalog, _status = await self.get(client)
        except Exception:
            logger.warning("custom_fields.values.catalog_unavailable", exc_info=True)
            return []

        published: list[ResolvedCustomFieldValueResponse] = []
        for stored in self._stored_rows(stored_values):
            resolved = self._with_catalog_definition(stored, catalog)
            if resolved is None:
                continue
            if not self._included_by_filters(
                resolved,
                tabs=tabs,
                groups=groups,
                group_ids=group_ids,
                definition_ids=definition_ids,
                names=names,
            ):
                continue
            published.append(ResolvedCustomFieldValueResponse.from_dto(resolved))
        return published

    async def _unpin_in_flight(self, in_flight: asyncio.Future[CatalogResult]) -> None:
        async with self._lock:
            if self._in_flight is in_flight:
                self._in_flight = None

    async def _fetch(
        self, client: BackstopClient, in_flight: asyncio.Future[CatalogResult]
    ) -> CatalogResult:
        try:
            definitions = await fetch_custom_field_definitions(client)
        except Exception as error:
            if self._definitions is not None:
                logger.warning(
                    "custom_fields.schema.refresh_failed_serving_stale",
                    extra={
                        "fetched_at": (
                            self._freshness.marked_at.isoformat()
                            if self._freshness.marked_at
                            else None
                        ),
                    },
                    exc_info=True,
                )
                CUSTOM_FIELD_SCHEMA_LOADS.add(1, {"source": "stale"})
                self._freshness.mark()
                result: CatalogResult = (dict(self._definitions), "stale")
                in_flight.set_result(result)
                return result
            in_flight.set_exception(error)
            raise

        self._definitions = definitions
        self._freshness.mark()
        CUSTOM_FIELD_SCHEMA_LOADS.add(1, {"source": "backstop"})
        logger.info(
            "custom_fields.schema.refreshed",
            extra={"definitions": len(definitions)},
        )
        result = (dict(definitions), "ok")
        in_flight.set_result(result)
        return result

    def _stored_rows(self, stored_values: object) -> list[CustomFieldValueAttributes]:
        if not isinstance(stored_values, list):
            return []
        rows: list[CustomFieldValueAttributes] = []
        for item in cast(list[object], stored_values):
            if not isinstance(item, Mapping):
                continue
            try:
                rows.append(CustomFieldValueAttributes.model_validate(item))
            except ValidationError:
                logger.warning("custom_fields.values.unreadable", exc_info=True)
        return rows

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
        self,
        resolved: ResolvedCustomFieldValueDto,
        *,
        tabs: Sequence[str],
        groups: Sequence[str],
        group_ids: Sequence[int],
        definition_ids: Sequence[str],
        names: Sequence[str],
    ) -> bool:
        if tabs and not self._equals_ignore_case(resolved.tab_name, tabs):
            return False
        if groups and not self._equals_ignore_case(resolved.group_name, groups):
            return False
        if group_ids and resolved.group_id not in set(group_ids):
            return False
        if definition_ids and resolved.definition_id not in {
            entry.strip() for entry in definition_ids
        }:
            return False
        return not names or self._equals_ignore_case(resolved.name, names)

    def _equals_ignore_case(self, actual: str | None, wanted: Sequence[str]) -> bool:
        if actual is None:
            return False
        folded = actual.casefold()
        return any(entry.casefold() == folded for entry in wanted)
