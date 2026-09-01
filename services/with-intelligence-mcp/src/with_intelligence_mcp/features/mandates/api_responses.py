"""The vendor's mandate shapes, from the v3 schemas.

A mandate is a search: this investor is looking to allocate to that kind of strategy, at this
stage. `status` plus `sub_status` is what makes one actionable or not.
"""

from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from with_intelligence_mcp.features.investments import CurrencyAmountAttributes
from with_intelligence_mcp.features.investors import ClassificationAttributes
from with_intelligence_mcp.with_intelligence_client import SEQUENCE, SINGLE


class MandateAmountAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    amount: float | None = None
    currency: Annotated[CurrencyAmountAttributes | None, SINGLE] = None


class MandateStatusAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int | None = None
    name: str | None = None
    sub_status: Annotated[ClassificationAttributes | None, SINGLE] = None


class MandateServiceAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int | None = None
    name: str | None = None


class MandateReviewedAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    date: str | None = None


class MandateInvestorAttributes(BaseModel):
    """Carries no name — the mandate identifies its investor by id only."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int | None = None
    aum: float | None = None
    type: Annotated[ClassificationAttributes | None, SINGLE] = None


class MandateNoteAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    date: str | None = None
    note: str | None = None


class MandateListItemAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int
    updated_at: str | None = None


class MandateExtendedAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int
    updated_at: str | None = None
    amount: Annotated[MandateAmountAttributes | None, SINGLE] = None
    status: Annotated[MandateStatusAttributes | None, SINGLE] = None
    service: Annotated[MandateServiceAttributes | None, SINGLE] = None
    last_reviewed: Annotated[MandateReviewedAttributes | None, SINGLE] = None
    institutional_investor: Annotated[MandateInvestorAttributes | None, SINGLE] = None
    fund: Annotated[ClassificationAttributes | None, SINGLE] = None
    primary_consultant_firm: Annotated[ClassificationAttributes | None, SINGLE] = None
    consultant: str | None = None
    rfp_link: str | None = None
    note: str | None = None
    notes: Annotated[list[MandateNoteAttributes], SEQUENCE] = Field(default_factory=list)
    asset_class: Annotated[list[ClassificationAttributes], SEQUENCE] = Field(default_factory=list)
    primary_strategies: Annotated[list[ClassificationAttributes], SEQUENCE] = Field(
        default_factory=list
    )
    secondary_strategies: Annotated[list[ClassificationAttributes], SEQUENCE] = Field(
        default_factory=list
    )
    fund_structures: Annotated[list[ClassificationAttributes], SEQUENCE] = Field(
        default_factory=list
    )
    market_focuses: Annotated[list[ClassificationAttributes], SEQUENCE] = Field(
        default_factory=list
    )
