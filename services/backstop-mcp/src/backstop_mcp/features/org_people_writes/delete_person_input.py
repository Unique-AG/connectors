"""`delete_person` input: the same identity as `update_person`. Delete is permanent."""

from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from backstop_mcp.features.elicitation_utils import CONFIRM_FIELD_DESCRIPTION, REFUSE_BULK_DELETE
from backstop_mcp.features.party_resolver import (
    PARTY_ID_REQUIRES_SEARCH_TYPE_DESCRIPTION,
    SEARCH_REQUIRES_SEARCH_TYPE_DESCRIPTION,
    blank_to_none,
    require_exactly_one_party_selector,
)
from backstop_mcp.models import NonEmptyStr

__all__ = [
    "DELETE_PERSON_INPUT_DESCRIPTION",
    "DeletePersonInput",
]

DELETE_PERSON_INPUT_DESCRIPTION = (
    "Required. The person to hard-delete. Needs exactly one of `party_id` or `search`, "
    + "plus `search_type` (defaults to people). Deletion is permanent: Backstop has no "
    + "recycle bin, and contact-locations are deleted first (`include=contactLocations`, "
    + "never `include=locations`). The tool asks the user to confirm when the client can "
    + "show a form (MCP 2026-07-28+). On an older protocol it returns `needs_confirmation` "
    + "so the model can ask in chat and retry with `confirm=true`. When the client never "
    + "advertised elicitation, it deletes immediately. Never invent an id. "
    + REFUSE_BULK_DELETE
)

_PERSON_SEARCH_TYPE_DESCRIPTION = (
    "Collection to resolve against. Echo `search_type` from a prior resolve when retrying "
    "with `party_id` — a contact or employee id is not a people id. Defaults to people."
)


class DeletePersonInput(BaseModel):
    """Hard-delete a CRM person after removing their contact-locations."""

    search_type: Literal["people", "contacts", "employees"] = Field(
        default="people", description=_PERSON_SEARCH_TYPE_DESCRIPTION
    )
    party_id: NonEmptyStr | None = Field(
        default=None, description=PARTY_ID_REQUIRES_SEARCH_TYPE_DESCRIPTION
    )
    search: NonEmptyStr | None = Field(
        default=None, description=SEARCH_REQUIRES_SEARCH_TYPE_DESCRIPTION
    )
    confirm: bool = Field(default=False, description=CONFIRM_FIELD_DESCRIPTION)

    @field_validator("party_id", "search", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        return blank_to_none(value)

    @model_validator(mode="after")
    def _exactly_one_selector(self) -> Self:
        require_exactly_one_party_selector(party_id=self.party_id, search=self.search)
        return self
