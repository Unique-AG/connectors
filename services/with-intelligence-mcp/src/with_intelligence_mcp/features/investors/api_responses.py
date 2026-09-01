"""The vendor's wire shapes, 1:1 with their field names, and lenient by default.

Only the fields the tools use are declared: `extra="ignore"` means the rest of a 40-field
`InvestorExtended` record is carried past us rather than breaking parsing when it changes.
"""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class ClassificationAttributes(BaseModel):
    """The vendor's generic `{id, name}` reference, used for every vocabulary value."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int | None = None
    name: str | None = None


class EntityAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int | None = None
    name: str | None = None


class LatestAumAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    value: float | None = None
    date: str | None = None
    currency: str | None = None


class AddressAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    city: str | None = None
    country: str | None = None
    state: str | None = None


class InvestorListItemAttributes(BaseModel):
    """What a listing returns: identity only."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int
    name: str | None = None
    updated_at: str | None = None


class InvestorExtendedAttributes(BaseModel):
    """What `GET /v3/investors/{id}` returns."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int
    name: str | None = None
    updated_at: str | None = None
    summary: str | None = None
    family_profile: str | None = None
    website: str | None = None
    year_of_incorporation: int | None = None
    aum: float | None = None
    latest_aum: LatestAumAttributes | None = None
    currency: ClassificationAttributes | None = None
    type: ClassificationAttributes | None = None
    address: AddressAttributes | None = None
    contacts_total: int | None = None
    contacts: list[EntityAttributes] = Field(default_factory=list)
    managers: list[ClassificationAttributes] = Field(default_factory=list)
    consultants: list[ClassificationAttributes] = Field(default_factory=list)
    asset_classes: list[ClassificationAttributes] = Field(default_factory=list)
    primary_strategies: list[ClassificationAttributes] = Field(default_factory=list)
    secondary_strategies: list[ClassificationAttributes] = Field(default_factory=list)
    investment_regions: list[ClassificationAttributes] = Field(default_factory=list)
    investment_countries: list[ClassificationAttributes] = Field(default_factory=list)
    investment_fund_structures: list[ClassificationAttributes] = Field(default_factory=list)
    investment_instruments: list[ClassificationAttributes] = Field(default_factory=list)
    investment_capital_structures: list[ClassificationAttributes] = Field(default_factory=list)

    # Present only for accounts licensed for the Intentions & Preferences add-on, so its absence
    # is not the same as an investor having stated none.
    preferences: dict[str, object] | None = None
