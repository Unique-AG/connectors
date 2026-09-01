"""The vendor's wire shapes, taken field-for-field from the v3 OpenAPI spec.

Only the fields the tools use are declared, and `extra="ignore"` carries the rest of a 40-field
record past us rather than breaking when it changes. Nested shapes are the spec's own, which is
not a detail: `address.country` is an object rather than a string, `latest_aum` dates its value
in `as_of`, `currency` names itself `short_name`, and an `Entity` carries an id and nothing else.
"""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class ClassificationAttributes(BaseModel):
    """The vendor's `{id, name}` reference, used for most vocabulary values."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int | None = None
    name: str | None = None


class EntityAttributes(BaseModel):
    """An id and nothing else. The vendor uses it where a name would need another endpoint."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int | None = None


class CurrencyAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int | None = None
    short_name: str | None = None


class StateAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int | None = None
    name: str | None = None
    abbreviation: str | None = None


class LatestAumAttributes(BaseModel):
    """Carries no currency of its own — `value_usd` is the normalised figure."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    value: float | None = None
    value_usd: float | None = None
    as_of: str | None = None


class AddressAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    city: str | None = None
    postcode: str | None = None
    state: StateAttributes | None = None
    country: ClassificationAttributes | None = None
    continent: ClassificationAttributes | None = None


class ConsultantAttributes(BaseModel):
    """Richer than a plain classification: it says whether the consultant leads the account."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int | None = None
    name: str | None = None
    is_lead: bool | None = None
    role_extended: str | None = None


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
    currency: CurrencyAttributes | None = None
    type: ClassificationAttributes | None = None
    address: AddressAttributes | None = None
    contacts_total: int | None = None

    # `Entity` — ids only. Names and titles come from `/v3/persons`.
    contacts: list[EntityAttributes] = Field(default_factory=list)
    investment_capital_structures: list[EntityAttributes] = Field(default_factory=list)

    managers: list[ClassificationAttributes] = Field(default_factory=list)
    asset_classes: list[ClassificationAttributes] = Field(default_factory=list)
    primary_strategies: list[ClassificationAttributes] = Field(default_factory=list)
    secondary_strategies: list[ClassificationAttributes] = Field(default_factory=list)
    investment_regions: list[ClassificationAttributes] = Field(default_factory=list)
    investment_countries: list[ClassificationAttributes] = Field(default_factory=list)
    investment_fund_structures: list[ClassificationAttributes] = Field(default_factory=list)
    investment_instruments: list[ClassificationAttributes] = Field(default_factory=list)
    consultants: list[ConsultantAttributes] = Field(default_factory=list)

    # Present only for accounts licensed for the Intentions & Preferences add-on, so its absence
    # is not the same as an investor having stated none.
    preferences: dict[str, object] | None = None
