"""`delete_person` input: a trusted person id. Delete is permanent."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from backstop_mcp.features.elicitation_utils import REFUSE_BULK_DELETE
from backstop_mcp.features.party_resolver import blank_to_none
from backstop_mcp.models import NonEmptyStr

__all__ = [
    "DELETE_PERSON_INPUT_DESCRIPTION",
    "DeletePersonInput",
]

DELETE_PERSON_INPUT_DESCRIPTION = (
    "Required. The person to hard-delete. Needs a trusted `party_id` "
    + "(search_type defaults to people). Deletion is permanent: Backstop has no "
    + "recycle bin. The tool removes the person's locations, then the person. It reads "
    + "the record and asks the user to confirm when the client can elicit; otherwise it "
    + "deletes immediately. Never invent an id. "
    + REFUSE_BULK_DELETE
)

_PERSON_SEARCH_TYPE_DESCRIPTION = (
    "Collection the id belongs to. Echo `search_type` from a prior resolve when it is "
    "not people — a contact or employee id is not a people id. Defaults to people."
)


class DeletePersonInput(BaseModel):
    """Hard-delete a CRM person after removing their locations."""

    search_type: Literal["people", "contacts", "employees"] = Field(
        default="people", description=_PERSON_SEARCH_TYPE_DESCRIPTION
    )
    party_id: NonEmptyStr = Field(
        description=(
            "Trusted Backstop person id from a prior tool. Echo `search_type` when it "
            "is not people. Never invent or guess."
        )
    )

    @field_validator("party_id", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        return blank_to_none(value)
