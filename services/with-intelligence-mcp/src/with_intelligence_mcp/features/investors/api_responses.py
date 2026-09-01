"""The vendor's wire shapes, taken field-for-field from the v3 OpenAPI spec.

Only the fields the tools use are declared, and `extra="ignore"` carries the rest of a 40-field
record past us rather than breaking when it changes. Nested shapes are the spec's own, which is
not a detail: `address.country` is an object rather than a string, `latest_aum` dates its value
in `as_of`, `currency` names itself `short_name`, and an `Entity` carries an id and nothing else.
"""

from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from with_intelligence_mcp.with_intelligence_client import SEQUENCE


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


class AumRangeAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    label: str | None = None


class LatestAumAttributes(BaseModel):
    """Carries no currency of its own — `value_usd` is the normalised figure.

    Both figures are in **millions**: a fund reporting 135,900 here is a $135.9bn fund, which
    `ranges_usd[].label` states in words ("> $50bn").
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    value: float | None = None
    value_usd: float | None = None
    as_of: str | None = None
    ranges_usd: Annotated[list[AumRangeAttributes], SEQUENCE] = Field(default_factory=list)


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


class StrategyGroupAttributes(BaseModel):
    """One primary strategy with the secondaries recorded under it."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    primary_strategy: ClassificationAttributes | None = None
    secondary_strategies: Annotated[list[ClassificationAttributes], SEQUENCE] = Field(
        default_factory=list
    )


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
    contacts: Annotated[list[EntityAttributes], SEQUENCE] = Field(default_factory=list)
    investment_capital_structures: Annotated[list[EntityAttributes], SEQUENCE] = Field(
        default_factory=list
    )

    managers: Annotated[list[ClassificationAttributes], SEQUENCE] = Field(default_factory=list)
    asset_classes: Annotated[list[ClassificationAttributes], SEQUENCE] = Field(default_factory=list)
    primary_strategies: Annotated[list[ClassificationAttributes], SEQUENCE] = Field(
        default_factory=list
    )
    secondary_strategies: Annotated[list[ClassificationAttributes], SEQUENCE] = Field(
        default_factory=list
    )
    investment_regions: Annotated[list[ClassificationAttributes], SEQUENCE] = Field(
        default_factory=list
    )
    investment_countries: Annotated[list[ClassificationAttributes], SEQUENCE] = Field(
        default_factory=list
    )
    investment_fund_structures: Annotated[list[ClassificationAttributes], SEQUENCE] = Field(
        default_factory=list
    )
    investment_instruments: Annotated[list[ClassificationAttributes], SEQUENCE] = Field(
        default_factory=list
    )

    # Declared an array, delivered as an index-keyed object.
    consultants: Annotated[list[ConsultantAttributes], SEQUENCE] = Field(default_factory=list)

    # The structured view of what they allocate to, and the one worth reading: the flat
    # `primary_strategies` mixes every asset class's strategies into one list.
    investment_strategies: Annotated[list[StrategyGroupAttributes], SEQUENCE] = Field(
        default_factory=list
    )

    # Present only for accounts licensed for the Intentions & Preferences add-on, so its absence
    # is not the same as an investor having stated none.
    preferences: dict[str, object] | None = None
