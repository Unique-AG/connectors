"""Published custom-field catalog and resolved-value response models."""

from typing import ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.features.custom_fields.entity_types import CustomFieldEntityType
from backstop_mcp.features.custom_fields.internal_dto import (
    CustomFieldDefinitionDto,
    CustomFieldEntityReferenceDto,
    CustomFieldGroupDto,
    CustomFieldGroupParentDto,
    ResolvedCustomFieldValueDto,
)
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.models import OmitNoneModel

__all__ = [
    "CustomFieldDefinitionResponse",
    "CustomFieldEntityReferenceResponse",
    "CustomFieldGroupMemberResponse",
    "CustomFieldGroupParentResponse",
    "CustomFieldGroupResponse",
    "ListCustomFieldGroupsResponse",
    "ListCustomFieldsResponse",
    "ResolvedCustomFieldValueResponse",
]


class CustomFieldDefinitionResponse(BaseModel):
    """One custom-field definition in the standard Backstop catalog returned to MCP callers."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str = Field(description="Backstop id of this custom-field definition.")
    name: str = Field(description="Field name as it appears on a record.")
    entity_type: str = Field(
        description=(
            "Standard Backstop Bean identifying the entity this field belongs to, such as a "
            "party or concrete Backstop entity resource."
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
        default=None,
        description="Name of the Backstop layout group this field sits in, when available.",
    )
    group_id: int | None = Field(
        default=None,
        description=(
            "Backstop identifier of the layout group this field sits in, when available. "
            "Definitions with the same group_id share a layout group."
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
    def from_definition(cls, definition: CustomFieldDefinitionDto) -> Self:
        """Project an internal catalog definition onto the published response shape."""
        return cls(
            id=definition.id,
            name=definition.name,
            entity_type=definition.entity_type,
            field_type=definition.field_type,
            field_type_display=definition.field_type_display,
            is_time_series=definition.is_time_series,
            select_options=list(definition.select_options),
            tab_name=definition.tab_name,
            group_name=definition.group_name,
            group_id=definition.group_id,
            layout_name=definition.layout_name,
            resource_type=definition.resource_type,
            required=definition.required,
            client_required=definition.client_required,
            system_defined=definition.system_defined,
            description=definition.description,
        )


class CustomFieldGroupParentResponse(BaseModel):
    """Immediate parent group as it appears on the Backstop row."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str | None = Field(
        default=None,
        description="Backstop id of the parent layout group, when published.",
    )
    name: str | None = Field(
        default=None,
        description="Name of the parent layout group, when published.",
    )
    parent_id: str | None = Field(
        default=None,
        description="Backstop id of the parent's parent, when the parent is itself nested.",
    )

    @classmethod
    def from_parent(cls, parent: CustomFieldGroupParentDto) -> Self:
        return cls(id=parent.id, name=parent.name, parent_id=parent.parent_id)


class CustomFieldGroupMemberResponse(BaseModel):
    """A custom-field definition that sits in a layout group."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str = Field(description="Backstop id of this custom-field definition.")
    name: str = Field(description="Field name as it appears on a record.")
    entity_type: str = Field(
        description=(
            "Standard Backstop Bean identifying the entity this field belongs to, such as a "
            "party or concrete Backstop entity resource."
        )
    )
    field_type: str | None = Field(
        default=None, description="Machine type of the field, as Backstop stores it."
    )

    @classmethod
    def from_definition(cls, definition: CustomFieldDefinitionDto) -> Self:
        return cls(
            id=definition.id,
            name=definition.name,
            entity_type=definition.entity_type,
            field_type=definition.field_type,
        )


class CustomFieldGroupResponse(BaseModel):
    """One layout group in the standard Backstop catalog returned to MCP callers."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str = Field(description="Backstop id of this layout group.")
    name: str = Field(description="Group name as Backstop publishes it.")
    full_path_name: list[str] = Field(
        description=(
            "Layout path segments from the root tab down to this group, as Backstop publishes "
            "them. The last segment is this group; earlier segments are its ancestors."
        )
    )
    parent: CustomFieldGroupParentResponse | None = Field(
        default=None,
        description=(
            "Immediate parent group when this group is nested. Absent fields stay null when "
            "Backstop omits them. Root groups have no parent."
        ),
    )
    membership: list[CustomFieldGroupMemberResponse] = Field(
        description=(
            "Custom-field definitions whose group_id matches this group. Empty when no "
            "definition sits in the group. Definitions without a group_id are not listed here."
        )
    )

    @classmethod
    def from_group(
        cls,
        group: CustomFieldGroupDto,
        membership: list[CustomFieldGroupMemberResponse],
    ) -> Self:
        parent = group.parent
        return cls(
            id=group.id,
            name=group.name,
            full_path_name=list(group.full_path_name),
            parent=None if parent is None else CustomFieldGroupParentResponse.from_parent(parent),
            membership=list(membership),
        )


class CustomFieldEntityReferenceResponse(OmitNoneModel):
    """A resolvable reference stored in an ENTITY-typed custom-field value."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str = Field(description="Backstop id of the referenced record. Echo it; never invent one.")
    resource_type: str | None = Field(
        default=None,
        description="JSON:API type of the referenced record, as Backstop stored it.",
    )
    resource_link: str | None = Field(
        default=None,
        description="Backstop API URL of the referenced record, when published.",
    )
    search_type: SearchType | None = Field(
        default=None,
        description=(
            "Party collection to echo into get_person or get_organization when resource_type "
            "is organizations, people, contacts, or employees. Omitted for other resource "
            "types — do not guess a party type."
        ),
    )

    @classmethod
    def from_dto(cls, reference: CustomFieldEntityReferenceDto) -> Self:
        return cls(
            id=reference.id,
            resource_type=reference.resource_type,
            resource_link=reference.resource_link,
            search_type=reference.search_type,
        )


class ResolvedCustomFieldValueResponse(OmitNoneModel):
    """One custom-field value joined to its catalog definition."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    definition_id: str = Field(
        description="Backstop id of the custom-field definition this value belongs to."
    )
    name: str = Field(description="Field name as it appears on the record.")
    layout_name: str | None = Field(
        default=None,
        description="Backstop layout this field belongs to, when published.",
    )
    group_name: str | None = Field(
        default=None,
        description="Name of the Backstop layout group this field sits in, when available.",
    )
    field_type: str | None = Field(
        default=None, description="Machine type of the field, as Backstop stores it."
    )
    tab_name: str | None = Field(
        default=None,
        description="Backstop layout tab this field sits on, when published.",
    )
    group_id: int | None = Field(
        default=None,
        description=(
            "Backstop identifier of the layout group this field sits in, when available. "
            "Definitions with the same group_id share a layout group."
        ),
    )
    entity_type: str | None = Field(
        default=None,
        description=(
            "Standard Backstop Bean identifying the entity this field belongs to, such as a "
            "party or a concrete Backstop entity resource."
        ),
    )
    value: CustomFieldEntityReferenceResponse | object = Field(
        default=None,
        description=(
            "Stored value for this field. ENTITY-typed values are a resolvable reference "
            "(id, resource_type, optional resource_link; search_type when the resource is a "
            "party collection). Other types are passed through as stored."
        ),
    )
    outside_current_options: bool | None = Field(
        default=None,
        description=(
            "True when this field has select options and the stored value is not among them. "
            "Omitted when the value is in the current options or the field has no option list. "
            "The stored value is kept either way."
        ),
    )

    @classmethod
    def from_dto(cls, resolved: ResolvedCustomFieldValueDto) -> Self:
        value: CustomFieldEntityReferenceResponse | object = resolved.value
        if isinstance(value, CustomFieldEntityReferenceDto):
            value = CustomFieldEntityReferenceResponse.from_dto(value)
        return cls(
            definition_id=resolved.definition_id,
            name=resolved.name,
            layout_name=resolved.layout_name,
            group_name=resolved.group_name,
            field_type=resolved.field_type,
            tab_name=resolved.tab_name,
            group_id=resolved.group_id,
            entity_type=resolved.entity_type,
            value=value,
            outside_current_options=resolved.outside_current_options or None,
        )


class ListCustomFieldsResponse(BaseModel):
    """Custom-field definitions grouped by the requested entity types."""

    status: Literal["ok"] = Field(default="ok", description="Always 'ok'.")
    cache: Literal["ok", "stale"] = Field(
        description=(
            "'ok' when the catalog was fetched this call or is still fresh; 'stale' when a "
            "previous catalog is served because refresh failed."
        )
    )
    definitions_by_entity: dict[CustomFieldEntityType, list[CustomFieldDefinitionResponse]] = Field(
        description=(
            "Custom-field definitions keyed by the requested standard Backstop entity type. "
            "An entity with no definitions is still present with an empty list. Definitions may "
            "be associated with a party or a concrete Backstop entity resource and include layout "
            "group metadata such as group_id when available."
        )
    )


class ListCustomFieldGroupsResponse(BaseModel):
    """Layout groups from the standard Backstop custom-field group catalog."""

    status: Literal["ok"] = Field(default="ok", description="Always 'ok'.")
    cache: Literal["ok", "stale"] = Field(
        description=(
            "'ok' when both catalogs were fetched this call or are still fresh; 'stale' when a "
            "previous catalog is served because refresh failed."
        )
    )
    groups: list[CustomFieldGroupResponse] = Field(
        description=(
            "Layout groups in catalog order. Each group's full_path_name is the tab-to-section "
            "path Backstop publishes, parent is the immediate parent group when nested, and "
            "membership is the definitions whose group_id matches this group. Groups with no "
            "matching definitions are still present with an empty membership list."
        )
    )
