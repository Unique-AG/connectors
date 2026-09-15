"""POST fields for `create_opportunity`.

`name`, `currency_code`, `is_erisa` and the investor identity are required — the measured
minimal 201 body. Investor is a party (`party_id` / `search` / `search_type`), never a
raw id. `stage` is an optional name accepted on create. There is no `opportunity_id`,
`stage_effective_date`, notify-list, or `investor_id` field. Custom fields go through
`update_custom_field_values`.
"""

from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from backstop_mcp.features.opportunity_writes._opportunity_writable_fields import (
    _OpportunityWritableFields,
)
from backstop_mcp.features.party_resolver import (
    PARTY_ID_REQUIRES_SEARCH_TYPE_DESCRIPTION,
    SEARCH_REQUIRES_SEARCH_TYPE_DESCRIPTION,
    blank_to_none,
    require_exactly_one_party_selector,
)
from backstop_mcp.models import NonEmptyStr

__all__ = [
    "CREATE_OPPORTUNITY_INPUT_DESCRIPTION",
    "CreateOpportunityInput",
]

CREATE_OPPORTUNITY_INPUT_DESCRIPTION = (
    "Required. The opportunity to create. `name`, `currency_code`, `is_erisa`, and the "
    "investor identity are required. Investor identity is the same as `get_person`: "
    "exactly one of `party_id` or `search`, plus `search_type` (defaults to contacts). "
    "`stage` is a stage name from this instance's vocabulary, not an id. Custom fields "
    "go through `update_custom_field_values`. To change an existing deal, use "
    "`update_opportunity`. Never invent an id."
)

_INVESTOR_SEARCH_TYPE_DESCRIPTION = (
    "Collection to resolve the investor against. Echo `search_type` from a prior resolve "
    "when retrying with `party_id` — a people or employee id is not a contacts id. "
    "Defaults to contacts. The POST relationship is always a `contacts` pointer."
)


class _CreateOpportunityIdentity(BaseModel):
    """Investor selectors. Listed last in the subclass bases so they lead the schema."""

    search_type: Literal["people", "contacts", "employees"] = Field(
        default="contacts", description=_INVESTOR_SEARCH_TYPE_DESCRIPTION
    )
    party_id: NonEmptyStr | None = Field(
        default=None, description=PARTY_ID_REQUIRES_SEARCH_TYPE_DESCRIPTION
    )
    search: NonEmptyStr | None = Field(
        default=None, description=SEARCH_REQUIRES_SEARCH_TYPE_DESCRIPTION
    )

    @field_validator("party_id", "search", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        return blank_to_none(value)

    @model_validator(mode="after")
    def _exactly_one_investor_selector(self) -> Self:
        require_exactly_one_party_selector(party_id=self.party_id, search=self.search)
        return self


class _CreateOpportunityRequired(BaseModel):
    """Required create fields. Listed before identity so they follow it in the schema."""

    name: NonEmptyStr = Field(description="Required. Deal name.")
    currency_code: NonEmptyStr = Field(description="Required. ISO currency code, e.g. USD.")
    is_erisa: bool = Field(description="Required. Whether the deal is ERISA.")


class CreateOpportunityInput(
    _OpportunityWritableFields, _CreateOpportunityRequired, _CreateOpportunityIdentity
):
    """POST an opportunity. Only supplied optional fields are sent."""
