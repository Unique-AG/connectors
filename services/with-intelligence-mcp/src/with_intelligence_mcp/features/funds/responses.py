from typing import Literal, Self

from pydantic import Field

from with_intelligence_mcp.features.funds.api_responses import FundExtendedAttributes
from with_intelligence_mcp.models import OmitNoneModel
from with_intelligence_mcp.utils import html_to_markdown, names, when_either, when_present


class FundProfileResponse(OmitNoneModel):
    """One fund: who runs it, what it trades, and the terms an allocator would ask about.

    `aum_millions` uses With Intelligence's millions unit. `minimum_investment` does not — it is
    an amount in `minimum_investment_currency`. A field that is absent was not on the record.
    """

    id: int = Field(description="With Intelligence fund identifier.", examples=[8677])
    name: str | None = Field(default=None, description="Fund name.")
    updated_at: str | None = Field(
        default=None, description="When With Intelligence last changed this fund record."
    )
    manager: str | None = Field(default=None, description="Management company name.")
    manager_id: int | None = Field(
        default=None, description="With Intelligence id of the management company."
    )
    status: str | None = Field(
        default=None, description="Whether the fund is active, and in what sense."
    )
    sub_status: str | None = Field(
        default=None,
        description="More specific stage within `status`, such as open to investment.",
    )
    is_liquidated: bool | None = Field(
        default=None, description="True when the fund has been liquidated."
    )
    inferred: bool | None = Field(
        default=None,
        description=(
            "True when With Intelligence inferred the record rather than confirming it. "
            "Do not present an inferred fund as a verified product."
        ),
    )
    strategy: str | None = Field(default=None, description="Strategy description, as prose.")
    strategies: list[str] | None = Field(
        default=None, description="Primary and secondary strategies.", examples=[["Global Macro"]]
    )
    asset_classes: list[str] | None = Field(
        default=None, description="Asset classes the fund trades.", examples=[["Hedge Funds"]]
    )
    approaches: list[str] | None = Field(
        default=None, description="Investment approaches, such as discretionary."
    )
    structures: list[str] | None = Field(
        default=None, description="Fund structures.", examples=[["Commingled"]]
    )
    fund_types: list[str] | None = Field(
        default=None, description="Fund type, such as single manager."
    )
    capital_structures: list[str] | None = Field(
        default=None, description="Capital structures the fund uses."
    )
    investment_regions: list[str] | None = Field(
        default=None, description="Regions the fund invests in.", examples=[["Global"]]
    )
    primary_investment_region: str | None = Field(
        default=None, description="The fund's primary investment region."
    )
    domiciles: list[str] | None = Field(default=None, description="Onshore and offshore domiciles.")
    inception_date: str | None = Field(default=None, description="When the fund launched.")
    currency: str | None = Field(
        default=None, description="Currency of `aum_millions`.", examples=["USD"]
    )
    aum_millions: float | None = Field(
        default=None,
        description=(
            "Latest assets, in MILLIONS of `currency`. Do not report the raw number as a "
            "plain figure."
        ),
    )
    aum_as_of: str | None = Field(default=None, description="Date of `aum_millions`.")
    management_fee: str | None = Field(
        default=None, description="Management fee in With Intelligence's own wording."
    )
    performance_fee: str | None = Field(
        default=None, description="Performance fee in With Intelligence's own wording."
    )
    minimum_investment: float | None = Field(
        default=None,
        description="Minimum investment in `minimum_investment_currency`, not in millions.",
    )
    minimum_investment_currency: str | None = Field(
        default=None, description="Currency of `minimum_investment`.", examples=["USD"]
    )
    managed_account_offered: bool | None = Field(
        default=None, description="Whether the fund offers a managed account."
    )
    fundraising_stage: str | None = Field(
        default=None, description="Where the fund is in its raise."
    )
    redemption_frequency: str | None = Field(
        default=None, description="How often investors can redeem."
    )
    redemption_terms: str | None = Field(
        default=None, description="Redemption terms in With Intelligence's own wording."
    )
    redemption_notification_period: str | None = Field(
        default=None, description="Notice required before a redemption."
    )
    subscription_frequency: str | None = Field(
        default=None, description="How often investors can subscribe."
    )
    subscription_terms: str | None = Field(
        default=None, description="Subscription terms in With Intelligence's own wording."
    )
    lock_up: str | None = Field(
        default=None, description="Lock-up, in With Intelligence's own wording."
    )

    @classmethod
    def from_attributes(cls, attributes: FundExtendedAttributes) -> Self:
        manager = attributes.management_company
        status = attributes.fund_status
        return cls(
            id=attributes.id,
            name=attributes.name,
            updated_at=attributes.updated_at,
            manager=manager.name if manager else None,
            manager_id=manager.id if manager else None,
            status=status.name if status else None,
            sub_status=status.sub_status.name if status and status.sub_status else None,
            is_liquidated=attributes.is_liquidated,
            inferred=attributes.inferred,
            strategy=html_to_markdown(attributes.strategy_description),
            strategies=when_either(
                attributes,
                "primary_strategies",
                "secondary_strategies",
                names(attributes.primary_strategies) + names(attributes.secondary_strategies),
            ),
            asset_classes=when_present(
                attributes, "asset_classes", names(attributes.asset_classes)
            ),
            approaches=when_present(attributes, "approaches", names(attributes.approaches)),
            structures=when_present(
                attributes, "fund_structures", names(attributes.fund_structures)
            ),
            fund_types=when_present(attributes, "fund_type", names(attributes.fund_type)),
            capital_structures=when_present(
                attributes, "capital_structures", names(attributes.capital_structures)
            ),
            investment_regions=when_present(
                attributes, "investment_regions", names(attributes.investment_regions)
            ),
            primary_investment_region=(
                attributes.primary_investment_region.name
                if attributes.primary_investment_region
                else None
            ),
            domiciles=when_either(
                attributes,
                "domiciles_offshore",
                "domiciles_onshore",
                (
                    names(attributes.domiciles_offshore) + names(attributes.domiciles_onshore)
                    or None
                ),
            ),
            inception_date=attributes.inception_date,
            currency=attributes.currency.short_name if attributes.currency else None,
            aum_millions=attributes.latest_aum,
            aum_as_of=attributes.latest_aum_date,
            management_fee=attributes.management_fee,
            performance_fee=attributes.performance_fee,
            minimum_investment=attributes.investment_min_size,
            minimum_investment_currency=attributes.investment_min_currency,
            managed_account_offered=attributes.managed_account_offered,
            fundraising_stage=(
                attributes.fundraising_stage.name if attributes.fundraising_stage else None
            ),
            redemption_frequency=(
                attributes.redemption_frequency.name if attributes.redemption_frequency else None
            ),
            redemption_terms=attributes.redemption_terms,
            redemption_notification_period=attributes.redemption_notification_period,
            subscription_frequency=(
                attributes.subscription_frequency.name
                if attributes.subscription_frequency
                else None
            ),
            subscription_terms=attributes.subscription_terms,
            lock_up=_lock_up(attributes.lock_up),
        )


class FundCandidateResponse(OmitNoneModel):
    id: int
    name: str | None = None
    updated_at: str | None = None


class FundAmbiguousResponse(OmitNoneModel):
    """Several funds matched the name. Ask which one, then call again with `fund_id`."""

    status: Literal["ambiguous"] = "ambiguous"
    searched_for: str
    candidates: list[FundCandidateResponse] = Field(default_factory=list)
    total_matches: int = 0


class FundNotFoundResponse(OmitNoneModel):
    """Nothing matched. The name filter may need to be closer to the fund's registered name."""

    status: Literal["not_found"] = "not_found"
    searched_for: str
    hint: str | None = None


class FundNotEntitledResponse(OmitNoneModel):
    status: Literal["not_entitled"] = "not_entitled"
    searched_for: str
    hint: str | None = None


def _lock_up(value: str | None) -> str | None:
    if value is None or value.strip().lower() == "none":
        return None
    return value.strip()
