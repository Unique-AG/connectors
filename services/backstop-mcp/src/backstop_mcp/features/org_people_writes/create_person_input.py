"""POST fields for `create_person`.

`last_name` and `gender` are required — the measured minimal 201 body. Every other field
is optional. There is no identity input and no location block; those belong on
`update_person`. `category_ids` is the initial set (a new record has nothing to append
to). Custom fields go through `update_custom_field_values`.
"""

from pydantic import Field

from backstop_mcp.features.org_people_writes._person_writable_fields import _PersonWritableFields
from backstop_mcp.models import NonEmptyStr

__all__ = [
    "CREATE_PERSON_INPUT_DESCRIPTION",
    "CreatePersonInput",
]

CREATE_PERSON_INPUT_DESCRIPTION = (
    "Required. The person to create. `last_name` and `gender` are required. "
    "`job_title` is at most 140 characters. Custom fields go through "
    "`update_custom_field_values`. To change an existing person, use `update_person`. "
    "Never invent an id."
)

_CATEGORY_IDS_DESCRIPTION = (
    "Contact-category ids from `list_contact_categories` to assign on create. A new "
    "record has nothing to append to. Never invent or guess."
)


class CreatePersonInput(_PersonWritableFields):
    """POST a person. Only supplied optional fields are sent."""

    last_name: NonEmptyStr = Field(description="Required. Last name.")
    gender: NonEmptyStr = Field(description="Required. Gender.")
    category_ids: tuple[str, ...] = Field(default=(), description=_CATEGORY_IDS_DESCRIPTION)
