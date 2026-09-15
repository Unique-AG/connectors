"""Optional opportunity fields shared by create and update."""

from datetime import date

from pydantic import BaseModel, Field

from backstop_mcp.models import NonEmptyStr

__all__ = [
    "CURRENCY_CODE_DESCRIPTION",
    "IS_ERISA_DESCRIPTION",
    "NAME_DESCRIPTION",
    "_OpportunityWritableFields",
]

NAME_DESCRIPTION = "Replacement deal name."
CURRENCY_CODE_DESCRIPTION = "Replacement ISO currency code, e.g. USD."
IS_ERISA_DESCRIPTION = "Whether the deal is ERISA."


class _OpportunityWritableFields(BaseModel):
    """Fields optional on both `create_opportunity` and `update_opportunity`."""

    description: NonEmptyStr | None = Field(default=None, description="Deal description.")
    aliases: NonEmptyStr | None = Field(default=None, description="Aliases string.")
    other_id: NonEmptyStr | None = Field(default=None, description="External/other id.")
    classification: NonEmptyStr | None = Field(
        default=None,
        description="Deal classification (wire `type`) — not the JSON:API resource type.",
    )
    requested_amount: float | None = Field(
        default=None, description="Requested amount, in `currency_code`."
    )
    allocated_amount: float | None = Field(
        default=None, description="Allocated amount, in `currency_code`."
    )
    probability: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description=(
            "Likelihood as a fraction: 0.3 is 30%. Setting `stage` does not "
            "change this — pass it explicitly if the deal's probability should move."
        ),
    )
    expected_investment_date: date | None = Field(
        default=None, description="Expected investment day."
    )
    waitlist_id: int | None = Field(default=None, description="Waitlist id.")
    stage: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Stage **name** (e.g. IDD), resolved against this instance's vocabulary. "
            "A `closed` stage closes the deal automatically. On an existing deal this "
            "is how you move the stage."
        ),
    )
    product_id: NonEmptyStr | None = Field(
        default=None, description="Product id. Never invent or guess."
    )
    primary_contact_id: NonEmptyStr | None = Field(
        default=None,
        description="Primary contact people id. Never invent or guess.",
    )
    referral_source_id: NonEmptyStr | None = Field(
        default=None,
        description="Referral-source contact id (`contacts`). Never invent or guess.",
    )
    owner_login: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Owner of this deal: the colleague at our own firm. A "
            "`list_system_users` login (`userName`), not a system-user id. Same role as "
            "`representative` on `search_opportunities`."
        ),
    )
    investor_type_id: NonEmptyStr | None = Field(
        default=None, description="Investor-type id. Never invent or guess."
    )
