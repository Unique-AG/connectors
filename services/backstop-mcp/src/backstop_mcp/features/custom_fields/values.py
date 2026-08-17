import logging
from dataclasses import dataclass
from datetime import date
from typing import ClassVar
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.backstop_client import (
    BackstopApiResource,
    BackstopApiResourceDocument,
    BackstopClient,
)
from backstop_mcp.dates import parse_lenient_date
from backstop_mcp.features.custom_fields.entity_types import normalize_entity_type
from backstop_mcp.features.custom_fields.types import CustomFieldDefinition

logger = logging.getLogger(__name__)

_REGULAR_FIELDS = "regularCustomFieldValues,modifiedTimestamp,modifiedBy"


@dataclass(frozen=True)
class CustomFieldValueRead:
    """One custom-field value read from Backstop.

    Entity-level provenance (`as_of`) lands once `features.data_hygiene` does — this PR reads
    only the value itself.
    """

    value: object | None


class RegularCustomFieldValueAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    definition_id: str | None = Field(default=None, alias="definitionId")
    value: object | None = None


class EntityWithRegularCustomFieldsAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    regular_custom_field_values: list[RegularCustomFieldValueAttributes] | None = Field(
        default=None, alias="regularCustomFieldValues"
    )
    modified_timestamp: str | None = Field(default=None, alias="modifiedTimestamp")
    modified_by: object | None = Field(default=None, alias="modifiedBy")


class TimeSeriesCustomFieldValueAttributes(BaseModel):
    """Wire shape for a `timeSeriesCustomFieldValues` entry.

    Field names follow the swagger's create example for
    `/{entity}/{id}/timeSeriesCustomFieldValues`, whose attributes are `definitionId`,
    `effectiveDate`, `otherId` and `value`.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    definition_id: str | None = Field(default=None, alias="definitionId")
    value: object | None = None
    # Kept as the raw string and parsed when ordering, rather than typed as `date`. A strict
    # `date` would turn one oddly-formatted entry into a schema error that fails the whole read
    # — worse than the mis-ordering it fixes, for a field we only need in order to sort.
    effective_date: str | None = Field(default=None, alias="effectiveDate")


type TimeSeriesResource = BackstopApiResource[TimeSeriesCustomFieldValueAttributes]


def parse_effective_date(raw: str | None) -> date | None:
    """Parse an `effectiveDate`, tolerating the datetime form and non-padded month/day."""
    parsed = parse_lenient_date(raw)
    if parsed is None and raw is not None and str(raw).strip():
        logger.warning(
            "custom_fields.time_series.unparseable_effective_date",
            extra={"effective_date": raw},
        )
    return parsed


def _effective_date_key(resource: TimeSeriesResource) -> tuple[int, date, str]:
    """Order a series so the newest entry sorts last.

    Sorts on a parsed date, not the raw string: comparing strings silently mis-orders anything
    that isn't zero-padded ISO-8601 (`"2026-9-01" > "2026-10-01"` lexicographically, but October
    is later). Entries with no usable date sort first — they can't be shown to be the newest —
    tie-broken by id so the order is stable.
    """
    effective = parse_effective_date(resource.attributes.effective_date)
    if effective is None:
        return (0, date.min, resource.id)
    return (1, effective, resource.id)


def latest_time_series_value(resources: list[TimeSeriesResource]) -> object | None:
    if not resources:
        return None
    return max(resources, key=_effective_date_key).attributes.value


async def read_custom_field_value(
    client: BackstopClient,
    *,
    entity_type: str,
    entity_id: str,
    definition: CustomFieldDefinition,
) -> CustomFieldValueRead:
    """Read one custom field's current value, via the path selected by `isTimeSeries`.

    Choosing the wrong path returns nothing for a field that does exist, which is why the flag
    is honoured rather than guessed at.
    """
    entity = normalize_entity_type(entity_type)
    if entity is None:
        raise ValueError(f"Unknown entity type: {entity_type!r}")
    safe_id = quote(entity_id, safe="")

    if definition.is_time_series:
        value = await _read_time_series_value(
            client, entity=entity, safe_id=safe_id, definition=definition
        )
        return CustomFieldValueRead(value=value)
    return await _read_regular_value(client, entity=entity, safe_id=safe_id, definition=definition)


async def _read_time_series_value(
    client: BackstopClient,
    *,
    entity: str,
    safe_id: str,
    definition: CustomFieldDefinition,
) -> object | None:
    # The whole series is paged through (`max_records=None`) rather than capped: Backstop
    # documents no `sort=` for this sub-collection, so "latest" can only be decided after
    # seeing every entry. A cap would silently return the newest of an arbitrary prefix.
    page = await client.paginate(
        f"/{entity}/{safe_id}/timeSeriesCustomFieldValues",
        params={"filter[definitionId][eq]": definition.definition_id},
        max_records=None,
        schema=BackstopApiResource[TimeSeriesCustomFieldValueAttributes],
    )
    if not page.items:
        return None
    logger.debug(
        "custom_fields.time_series.read",
        extra={
            "definition_id": definition.definition_id,
            "entries": len(page.items),
        },
    )
    return latest_time_series_value(page.items)


async def _read_regular_value(
    client: BackstopClient,
    *,
    entity: str,
    safe_id: str,
    definition: CustomFieldDefinition,
) -> CustomFieldValueRead:
    document = await client.get(
        f"/{entity}/{safe_id}",
        params={"fields": _REGULAR_FIELDS},
        schema=BackstopApiResourceDocument[EntityWithRegularCustomFieldsAttributes],
    )
    attrs = document.data.attributes
    values = attrs.regular_custom_field_values or []
    for entry in values:
        if entry.definition_id == definition.definition_id:
            return CustomFieldValueRead(value=entry.value)
    return CustomFieldValueRead(value=None)
