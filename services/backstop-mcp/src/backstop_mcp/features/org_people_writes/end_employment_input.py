"""End one person↔organization employment by writing `endDate` only."""

from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from backstop_mcp.features.party_resolver import (
    PARTY_ID_REQUIRES_SEARCH_TYPE_DESCRIPTION,
    SEARCH_REQUIRES_SEARCH_TYPE_DESCRIPTION,
    blank_to_none,
    require_exactly_one_party_selector,
    require_path_segment,
)
from backstop_mcp.models import NonEmptyStr

__all__ = [
    "END_EMPLOYMENT_INPUT_DESCRIPTION",
    "EndEmploymentInput",
]

END_EMPLOYMENT_INPUT_DESCRIPTION = (
    "Required. The person, the organization, and the `end_date` to write. Person identity "
    "is the same as `get_person`: exactly one of `party_id` or `search`, plus `search_type`. "
    "Organization identity is exactly one of `organization_id` or `organization_search`. "
    "There is no relationship-id parameter — the command finds the employment row. An "
    "`end_date` of today is stored but the person still reads as a current contact until "
    "that date has passed. Never invent an id."
)

_PERSON_SEARCH_TYPE_DESCRIPTION = (
    "Collection to resolve the person against. Echo `search_type` from a prior resolve "
    "when retrying with `party_id` — a contact or employee id is not a people id. "
    "Defaults to people."
)


class EndEmploymentInput(BaseModel):
    """Resolve both parties and write `endDate` on the employment relationship."""

    search_type: Literal["people", "contacts", "employees"] = Field(
        default="people", description=_PERSON_SEARCH_TYPE_DESCRIPTION
    )
    party_id: NonEmptyStr | None = Field(
        default=None, description=PARTY_ID_REQUIRES_SEARCH_TYPE_DESCRIPTION
    )
    search: NonEmptyStr | None = Field(
        default=None, description=SEARCH_REQUIRES_SEARCH_TYPE_DESCRIPTION
    )
    organization_id: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Trusted Backstop organization id from a prior resolve. Exactly one of "
            "`organization_id` or `organization_search` must be provided. Never invent "
            "or guess."
        ),
    )
    organization_search: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Organization name to resolve when no trusted `organization_id` is available. "
            "Exactly one of `organization_id` or `organization_search` must be provided."
        ),
    )
    end_date: date = Field(
        description=(
            "Employment end date (YYYY-MM-DD). Written as `endDate` only. A date that is "
            "not strictly before today is stored, but our read path still reports the "
            "person as a current contact until it passes."
        )
    )

    @field_validator("party_id", "search", "organization_id", "organization_search", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        return blank_to_none(value)

    @model_validator(mode="after")
    def _exactly_one_person_selector(self) -> Self:
        require_exactly_one_party_selector(party_id=self.party_id, search=self.search)
        return self

    @model_validator(mode="after")
    def _exactly_one_organization_selector(self) -> Self:
        if (self.organization_id is None) == (self.organization_search is None):
            raise ValueError(
                "Exactly one of organization_id or organization_search must be provided"
            )
        if self.organization_id is not None:
            require_path_segment(self.organization_id, field_name="organization_id")
        return self
