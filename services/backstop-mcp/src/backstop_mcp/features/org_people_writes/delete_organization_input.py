"""`delete_organization` input: a trusted organization id. Delete is permanent."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from backstop_mcp.features.elicitation_utils import REFUSE_BULK_DELETE
from backstop_mcp.features.party_resolver import blank_to_none
from backstop_mcp.models import NonEmptyStr

__all__ = [
    "DELETE_ORGANIZATION_INPUT_DESCRIPTION",
    "DeleteOrganizationInput",
]

DELETE_ORGANIZATION_INPUT_DESCRIPTION = (
    "Required. The organization to hard-delete. Needs a trusted `party_id` "
    + "(search_type defaults to organizations). Deletion is permanent: Backstop has no "
    + "recycle bin. The tool removes the organization's locations, then the organization. "
    + "It reads the record and asks the user to confirm when the client can elicit; "
    + "otherwise it deletes immediately. Never invent an id. "
    + REFUSE_BULK_DELETE
)

_ORG_SEARCH_TYPE_DESCRIPTION = (
    "Echo `search_type` from a prior resolve. This tool only deletes organizations; "
    "omit it or pass `organizations`."
)


class DeleteOrganizationInput(BaseModel):
    """Hard-delete a CRM organization after removing its locations."""

    search_type: Literal["organizations"] = Field(
        default="organizations", description=_ORG_SEARCH_TYPE_DESCRIPTION
    )
    party_id: NonEmptyStr = Field(
        description=("Trusted Backstop organization id from a prior tool. Never invent or guess.")
    )

    @field_validator("party_id", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        return blank_to_none(value)
