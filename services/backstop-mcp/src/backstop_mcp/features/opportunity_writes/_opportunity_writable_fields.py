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

    description: NonEmptyStr | None = Field(
        default=None, description="Replacement deal description."
    )
    aliases: NonEmptyStr | None = Field(default=None, description="Replacement aliases string.")
    other_id: NonEmptyStr | None = Field(default=None, description="Replacement external/other id.")
    classification: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Replacement deal classification (wire `type`) — not the JSON:API resource type."
        ),
    )
    requested_amount: float | None = Field(
        default=None, description="Replacement requested amount, in `currency_code`."
    )
    allocated_amount: float | None = Field(
        default=None, description="Replacement allocated amount, in `currency_code`."
    )
    probability: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description=(
            "Replacement likelihood as a fraction: 0.3 is 30%. Setting `stage` does not "
            "change this — pass it explicitly if the deal's probability should move."
        ),
    )
    expected_investment_date: date | None = Field(
        default=None, description="Replacement expected investment day."
    )
    waitlist_id: int | None = Field(default=None, description="Replacement waitlist id.")
    stage: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Replacement stage **name** (e.g. IDD), resolved against this instance's "
            "vocabulary. This is the only way to move a deal's stage. A `closed` stage "
            "closes the deal automatically."
        ),
    )
    product_id: NonEmptyStr | None = Field(
        default=None, description="Replacement product id. Never invent or guess."
    )
    primary_contact_id: NonEmptyStr | None = Field(
        default=None,
        description="Replacement primary contact people id. Never invent or guess.",
    )
    referral_source_id: NonEmptyStr | None = Field(
        default=None,
        description="Replacement referral-source contact id (`contacts`). Never invent or guess.",
    )
    owner_login: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Replacement owner of this deal: the colleague at our own firm. A "
            "`list_system_users` login (`userName`), not a system-user id. Same role as "
            "`representative` on `search_opportunities`."
        ),
    )
    investor_type_id: NonEmptyStr | None = Field(
        default=None, description="Replacement investor-type id. Never invent or guess."
    )
