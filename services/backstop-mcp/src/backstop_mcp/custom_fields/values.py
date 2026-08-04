from __future__ import annotations

from typing import ClassVar
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.backstop_client.client import BackstopClient
from backstop_mcp.backstop_client.json_api import BackstopApiDocument, BackstopApiResource
from backstop_mcp.custom_fields.overrides import normalize_entity_type
from backstop_mcp.custom_fields.types import CustomFieldDefinition


class RegularCustomFieldValueAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    definition_id: str | None = Field(default=None, alias="definitionId")
    value: object | None = None


class EntityWithRegularCustomFieldsAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    regular_custom_field_values: list[RegularCustomFieldValueAttributes] | None = Field(
        default=None, alias="regularCustomFieldValues"
    )


class TimeSeriesCustomFieldValueAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    definition_id: str | None = Field(default=None, alias="definitionId")
    value: object | None = None
    effective_date: str | None = Field(default=None, alias="effectiveDate")
    date: str | None = None


async def read_custom_field_value(
    client: BackstopClient,
    *,
    entity_type: str,
    entity_id: str,
    definition: CustomFieldDefinition,
) -> object | None:
    """Read one custom field value using the path selected by `isTimeSeries`."""
    entity = normalize_entity_type(entity_type)
    safe_id = quote(entity_id, safe="")

    if definition.is_time_series:
        page = await client.paginate(
            f"/{entity}/{safe_id}/timeSeriesCustomFieldValues",
            params={"filter[definitionId][eq]": definition.definition_id},
            max_records=50,
            schema=BackstopApiResource[TimeSeriesCustomFieldValueAttributes],
        )
        if not page.items:
            return None

        def sort_key(
            resource: BackstopApiResource[TimeSeriesCustomFieldValueAttributes],
        ) -> str:
            attrs = resource.attributes
            return attrs.effective_date or attrs.date or ""

        items = sorted(page.items, key=sort_key)
        return items[-1].attributes.value

    document = await client.get(
        f"/{entity}/{safe_id}",
        params={"fields": "regularCustomFieldValues"},
        schema=BackstopApiDocument[EntityWithRegularCustomFieldsAttributes],
    )
    if document.data is None or isinstance(document.data, list):
        return None
    values = document.data.attributes.regular_custom_field_values or []
    for entry in values:
        if entry.definition_id == definition.definition_id:
            return entry.value
    return None
