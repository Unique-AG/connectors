"""With Intelligence's fund shapes, from the v3 schemas.

A fund is the product an investor holds. `fund_status.id` arrives as a string such as "ACTIVE",
so the id is not modelled — the name is what a caller can read.
"""

from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from with_intelligence_mcp.features.investors import ClassificationAttributes, CurrencyAttributes
from with_intelligence_mcp.with_intelligence_client import SEQUENCE, SINGLE


class FundStatusLabelAttributes(BaseModel):
    """A classification whose id is not a number on this record."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: str | None = None


class FundStatusAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: str | None = None
    sub_status: Annotated[FundStatusLabelAttributes | None, SINGLE] = None


class FundAssetClassAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int | None = None
    name: str | None = None


class FundListItemAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int
    name: str | None = None
    updated_at: str | None = None


class FundExtendedAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int
    name: str | None = None
    updated_at: str | None = None
    strategy_description: str | None = None
    inception_date: str | None = None
    is_liquidated: bool | None = None
    inferred: bool | None = None
    management_fee: str | None = None
    performance_fee: str | None = None
    lock_up: str | None = None
    redemption_terms: str | None = None
    redemption_notification_period: str | None = None
    subscription_terms: str | None = None
    investment_min_size: float | None = None
    investment_min_currency: str | None = None
    managed_account_offered: bool | None = None
    latest_aum: float | None = None
    latest_aum_date: str | None = None
    management_company: Annotated[ClassificationAttributes | None, SINGLE] = None
    currency: Annotated[CurrencyAttributes | None, SINGLE] = None
    fund_status: Annotated[FundStatusAttributes | None, SINGLE] = None
    fundraising_stage: Annotated[ClassificationAttributes | None, SINGLE] = None
    primary_investment_region: Annotated[ClassificationAttributes | None, SINGLE] = None
    redemption_frequency: Annotated[ClassificationAttributes | None, SINGLE] = None
    subscription_frequency: Annotated[ClassificationAttributes | None, SINGLE] = None
    primary_strategies: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = None
    secondary_strategies: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = None
    asset_classes: Annotated[list[FundAssetClassAttributes] | None, SEQUENCE] = None
    approaches: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = None
    fund_structures: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = None
    fund_type: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = None
    capital_structures: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = None
    domiciles_offshore: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = None
    domiciles_onshore: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = None
    investment_regions: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = Field(
        default=None
    )
