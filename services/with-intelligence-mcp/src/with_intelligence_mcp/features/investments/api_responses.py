"""The vendor's investment shapes, from the v3 schemas.

An investment is one position: this investor, in that fund, at that amount. `deleted_at` is how
an exited position is visible at all.
"""

from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from with_intelligence_mcp.features.investors import ClassificationAttributes
from with_intelligence_mcp.with_intelligence_client import SEQUENCE


class CurrencyAmountAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int | None = None
    short_name: str | None = None


class InvestmentAmountAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    amount: float | None = None
    date: str | None = None
    currency: CurrencyAmountAttributes | None = None


class InvestmentFundAttributes(BaseModel):
    """`unknown` marks a position whose fund the vendor could not identify."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int | None = None
    name: str | None = None
    unknown: bool | None = None


class InvestmentListItemAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int
    updated_at: str | None = None


class InvestmentExtendedAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int
    updated_at: str | None = None
    deleted_at: str | None = None
    latest_as_of: str | None = None
    amount: InvestmentAmountAttributes | None = None
    fund: InvestmentFundAttributes | None = None
    manager_firm: ClassificationAttributes | None = None
    institutional_investor: ClassificationAttributes | None = None
    asset_classes: Annotated[list[ClassificationAttributes], SEQUENCE] = Field(default_factory=list)
    fund_primary_strategies: Annotated[list[ClassificationAttributes], SEQUENCE] = Field(
        default_factory=list
    )
    fund_secondary_strategies: Annotated[list[ClassificationAttributes], SEQUENCE] = Field(
        default_factory=list
    )
    fund_structures: Annotated[list[ClassificationAttributes], SEQUENCE] = Field(
        default_factory=list
    )
