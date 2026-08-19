from collections.abc import Mapping
from typing import ClassVar, Self, cast

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.backstop_client import BackstopApiResource
from backstop_mcp.features.custom_fields.api_responses import CustomFieldDefinitionAttributes
from backstop_mcp.features.custom_fields.entity_types import custom_field_entity_type_from_bean

__all__ = ["CustomFieldDefinitionDto"]

_ENTRY_COLLECTION_KEYS = ("entries", "lovEntries", "viewableEntries", "options", "values")


class CustomFieldDefinitionDto(BaseModel):
    """A CRM custom-field definition from Backstop attributes."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str = Field(description="Backstop id of this custom-field definition.")
    name: str = Field(description="Field name as it appears on a record.")
    entity_type: str = Field(
        description=(
            "Backstop bean this field belongs to (e.g. 'Organization', 'Person'). The "
            "response groups definitions under the MCP entity-type key instead."
        )
    )
    field_type: str | None = Field(
        default=None, description="Machine type of the field, as Backstop stores it."
    )
    field_type_display: str | None = Field(
        default=None, description="Human-readable type label, when Backstop publishes one."
    )
    is_time_series: bool = Field(
        default=False, description="True when this field stores a time series of values."
    )
    select_options: list[object] = Field(
        default_factory=list,
        description="Picklist options when this is a select field; empty otherwise.",
    )
    tab_name: str | None = Field(
        default=None, description="Backstop layout tab this field sits on, when published."
    )
    group_name: str | None = Field(
        default=None, description="Backstop layout group this field sits in, when published."
    )
    layout_name: str | None = Field(
        default=None, description="Backstop layout this field belongs to, when published."
    )
    resource_type: str | None = Field(
        default=None, description="Backstop resource type of this definition, when published."
    )
    required: bool | None = Field(
        default=None, description="Whether Backstop marks this field as required."
    )
    client_required: bool | None = Field(
        default=None, description="Whether this instance marks this field as client-required."
    )
    system_defined: bool | None = Field(
        default=None,
        description="True when this is a Backstop-defined field, not tenant-defined.",
    )
    description: str | None = Field(
        default=None, description="Help text on the definition, when Backstop publishes one."
    )

    @classmethod
    def from_resource(
        cls, resource: BackstopApiResource[CustomFieldDefinitionAttributes]
    ) -> Self | None:
        """Map one CRM definition resource onto Backstop attributes.

        Returns None when `name` or `entityType` is missing, or `entityType` is not one of the
        six known Beans.
        """
        attrs = resource.attributes
        name = attrs.name
        if not name:
            return None

        entity_type = attrs.entity_type
        if not entity_type or custom_field_entity_type_from_bean(entity_type) is None:
            return None

        return cls(
            id=resource.id,
            name=name,
            entity_type=entity_type,
            field_type=attrs.field_type,
            field_type_display=attrs.field_type_display,
            is_time_series=bool(attrs.is_time_series),
            select_options=_select_options(attrs.select_options),
            tab_name=attrs.tab_name,
            group_name=attrs.group_name,
            layout_name=attrs.layout_name,
            resource_type=attrs.resource_type,
            required=attrs.required,
            client_required=attrs.client_required,
            system_defined=attrs.system_defined,
            description=attrs.description,
        )


def _select_options(value: object | None) -> list[object]:
    """Keep a list of inline picklist options, including object-shaped collections."""
    if isinstance(value, list):
        return list(cast(list[object], value))
    if not isinstance(value, Mapping):
        return []
    payload = cast(Mapping[str, object], value)
    for key in _ENTRY_COLLECTION_KEYS:
        items = payload.get(key)
        if isinstance(items, list) and items:
            return list(cast(list[object], items))
    raw_select = payload.get("selectOptions")
    if isinstance(raw_select, list) and raw_select:
        return list(cast(list[object], raw_select))
    raw_data = payload.get("data")
    if isinstance(raw_data, list):
        return list(cast(list[object], raw_data))
    if isinstance(raw_data, Mapping):
        return [dict(cast(Mapping[str, object], raw_data))]
    return []
