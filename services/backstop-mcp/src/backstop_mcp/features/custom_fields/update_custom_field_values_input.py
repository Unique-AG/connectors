"""Input for `POST /bulk-custom-field-values`. Fields are identified by definition id only."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from backstop_mcp.models import NonEmptyStr

__all__ = [
    "MAX_CUSTOM_FIELD_VALUES",
    "UPDATE_CUSTOM_FIELD_VALUES_INPUT_DESCRIPTION",
    "CustomFieldWriteEntityType",
    "UpdateCustomFieldValueInput",
    "UpdateCustomFieldValuesInput",
]

MAX_CUSTOM_FIELD_VALUES = 15

type CustomFieldWriteEntityType = Literal["people", "organizations", "opportunities"]

UPDATE_CUSTOM_FIELD_VALUES_INPUT_DESCRIPTION = (
    "Required. Custom-field values to write on one person, organization, or opportunity. "
    "Identify each field by `definition_id` from `list_custom_fields`, never by name — "
    "names collide (an opportunity has a custom field literally called Probability). "
    f"At most {MAX_CUSTOM_FIELD_VALUES} values. The entity id comes from get_person, "
    "get_organization, or get_opportunities."
)


class UpdateCustomFieldValueInput(BaseModel):
    """One custom-field value. `definition_id` is the catalog id, never a name."""

    definition_id: int = Field(
        description=(
            "Backstop custom-field definition id from `list_custom_fields`. Never a name: "
            "two definitions can share a name, and an opportunity has a custom field "
            "called Probability that is not the native probability attribute."
        )
    )
    value: object = Field(
        description=(
            "Value to store, in the shape the definition expects. `null` clears the field "
            "and is rejected on a required one. To leave a field as it is, omit its row "
            "from `values` — never send `null` for a field you mean to keep."
        )
    )
    effective_date: date | None = Field(
        default=None,
        description=(
            "Required for time-series definitions; rejected on regular ones. Branching "
            "comes from the catalog, not from this field being set."
        ),
    )


class UpdateCustomFieldValuesInput(BaseModel):
    """A batch of custom-field values for one existing entity."""

    entity_type: CustomFieldWriteEntityType = Field(
        description=(
            "Wire `resource.resourceType`: `people`, `organizations`, or `opportunities`. "
            "This tool does not resolve a party by name."
        )
    )
    entity_id: NonEmptyStr = Field(
        description=(
            "Backstop id of that entity. From `get_person`, `get_organization`, or "
            "`get_opportunities`. Never invent or guess."
        )
    )
    values: tuple[UpdateCustomFieldValueInput, ...] = Field(
        min_length=1,
        max_length=MAX_CUSTOM_FIELD_VALUES,
        description=(
            f"Values to write, 1 to {MAX_CUSTOM_FIELD_VALUES}. Each row is a definition "
            "id plus a value. Time-series rows also need `effective_date`. Only the fields "
            "listed here are touched: this is not a full-record replace, so do not pad the "
            "batch with fields you are not changing."
        ),
    )
