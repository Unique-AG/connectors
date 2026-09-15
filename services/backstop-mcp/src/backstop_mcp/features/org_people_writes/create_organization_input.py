"""POST fields for `create_organization`.

`name` is required and at most 50 characters. Every other field is optional. There is
no identity input and no location block; those belong on `update_organization`.
`category_ids` is the initial set (a new record has nothing to append to). Custom
fields go through `update_custom_field_values`.
"""

from pydantic import Field

from backstop_mcp.features.org_people_writes._organization_writable_fields import (
    _OrganizationWritableFields,
)
from backstop_mcp.models import NonEmptyStr

__all__ = [
    "CREATE_ORGANIZATION_INPUT_DESCRIPTION",
    "CreateOrganizationInput",
]

CREATE_ORGANIZATION_INPUT_DESCRIPTION = (
    "Required. The organization to create. `name` is required and at most 50 characters. "
    "Custom fields go through `update_custom_field_values`. To change an existing "
    "organization, use `update_organization`. Never invent an id."
)

_CATEGORY_IDS_DESCRIPTION = (
    "Contact-category ids to assign on create. A new record has nothing to append to. "
    "Never invent or guess."
)


class CreateOrganizationInput(_OrganizationWritableFields):
    """POST an organization. Only supplied optional fields are sent."""

    name: NonEmptyStr = Field(
        max_length=50,
        description=(
            "Required. Organization name. At most 50 characters — Backstop silently "
            "stores over-length values on this endpoint."
        ),
    )
    category_ids: tuple[str, ...] = Field(default=(), description=_CATEGORY_IDS_DESCRIPTION)
