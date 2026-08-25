from collections.abc import Mapping
from typing import ClassVar, Self, cast

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.backstop_client import BackstopApiResource
from backstop_mcp.features.custom_fields.api_responses import (
    CustomFieldDefinitionAttributes,
    CustomFieldGroupAttributes,
    CustomFieldGroupParentAttributes,
)
from backstop_mcp.features.custom_fields.entity_types import custom_field_entity_type_from_bean
from backstop_mcp.features.entity_types import SearchType

__all__ = [
    "CustomFieldDefinitionDto",
    "CustomFieldEntityReferenceDto",
    "CustomFieldGroupDto",
    "CustomFieldGroupParentDto",
    "ResolvedCustomFieldValueDto",
]

_ENTRY_COLLECTION_KEYS = ("entries", "lovEntries", "viewableEntries", "options", "values")


class CustomFieldDefinitionDto(BaseModel):
    """A CRM custom-field definition from Backstop attributes."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str = Field(description="Backstop id of this custom-field definition.")
    name: str = Field(description="Field name as it appears on a record.")
    entity_type: str = Field(
        description=(
            "Standard Backstop Bean identifying the entity this field belongs to, such as a "
            "party or concrete entity resource. The response groups definitions under the MCP "
            "entity-type key instead."
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
    group_id: int | None = Field(
        default=None,
        description=(
            "Backstop id of the layout group this field sits in, when published. "
            "Use it as the stable group identifier within this catalog."
        ),
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
        default=None, description="Whether Backstop marks this field as client-required."
    )
    system_defined: bool | None = Field(
        default=None,
        description="True when Backstop marks this field as system-defined.",
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
            group_id=attrs.group_id,
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


class CustomFieldGroupParentDto(BaseModel):
    """Immediate parent group as published on the row, without following a parent URL."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str | None = None
    name: str | None = None
    parent_id: str | None = None

    @classmethod
    def from_attributes(cls, attributes: CustomFieldGroupParentAttributes) -> Self:
        return cls(id=attributes.id, name=attributes.name or None, parent_id=attributes.parent_id)


class CustomFieldGroupDto(BaseModel):
    """A CRM layout group from Backstop `custom-field-groups` attributes."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str
    full_path_name: list[str]
    parent: CustomFieldGroupParentDto | None = None

    @classmethod
    def from_resource(
        cls, resource: BackstopApiResource[CustomFieldGroupAttributes]
    ) -> Self | None:
        """Map one layout-group resource. Returns None when `name` is missing."""
        name = resource.attributes.name
        if not name:
            return None
        parent = resource.attributes.parent
        return cls(
            id=resource.id,
            name=name,
            full_path_name=_path_segments(resource.attributes.full_path_name),
            parent=None if parent is None else CustomFieldGroupParentDto.from_attributes(parent),
        )


class CustomFieldEntityReferenceDto(BaseModel):
    """An ENTITY-typed custom-field value parsed from Backstop's inline resource ref."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    resource_type: str | None = None
    resource_link: str | None = None
    search_type: SearchType | None = None


class ResolvedCustomFieldValueDto(BaseModel):
    """One stored value with catalog metadata copied on, so a caller does not join again."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    definition_id: str
    name: str
    layout_name: str | None = None
    group_name: str | None = None
    field_type: str | None = None
    tab_name: str | None = None
    group_id: int | None = None
    entity_type: str | None = None
    value: object = None
    outside_current_options: bool = False

    @classmethod
    def from_definition(
        cls,
        definition: CustomFieldDefinitionDto,
        *,
        value: object,
        outside_current_options: bool,
    ) -> Self:
        return cls(
            definition_id=definition.id,
            name=definition.name,
            layout_name=definition.layout_name,
            group_name=definition.group_name,
            field_type=definition.field_type,
            tab_name=definition.tab_name,
            group_id=definition.group_id,
            entity_type=definition.entity_type,
            value=value,
            outside_current_options=outside_current_options,
        )


def _path_segments(value: list[object] | None) -> list[str]:
    if not value:
        return []
    segments: list[str] = []
    for item in value:
        if isinstance(item, str):
            stripped = item.strip()
            if stripped:
                segments.append(stripped)
    return segments
