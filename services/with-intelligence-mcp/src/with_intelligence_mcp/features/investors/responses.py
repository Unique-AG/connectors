"""What the tool returns to the model: trimmed, renamed where the vendor's naming misleads,
and documented for the model that reads it."""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class OmitNoneModel(BaseModel):
    """Drops unset fields from the payload, so a sparse record does not read as a wall of nulls."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    def serializable(self) -> dict[str, object]:
        return self.model_dump(exclude_none=True, exclude_defaults=False)


class NamedValueResponse(OmitNoneModel):
    id: int | None = Field(default=None, description="The vendor's id, for follow-up filters.")
    name: str | None = None


class AumResponse(OmitNoneModel):
    value_millions: float | None = Field(
        default=None,
        description=(
            "Total assets under management, in MILLIONS of `currency`. 135900 means 135.9 "
            "billion. Do not report it as a plain figure."
        ),
    )
    value_usd_millions: float | None = Field(
        default=None, description="The same figure in millions of USD."
    )
    band: str | None = Field(
        default=None, description="The vendor's own words for the size, e.g. '> $50bn'."
    )
    as_of: str | None = Field(default=None, description="Date the figure was reported.")
    currency: str | None = None


class StrategyGroupResponse(OmitNoneModel):
    """A primary strategy with the secondaries recorded under it."""

    primary: str | None = None
    secondary: list[str] = Field(default_factory=list)


class ConsultantResponse(OmitNoneModel):
    id: int | None = None
    name: str | None = None
    is_lead: bool | None = Field(
        default=None, description="Whether this consultant leads the relationship."
    )
    role: str | None = None


class InvestorProfileResponse(OmitNoneModel):
    """One institutional investor, as a meeting-prep sheet.

    `managers` is who they currently allocate to. A field that is absent is unknown to With
    Intelligence, not zero.
    """

    id: int
    name: str | None = None
    investor_type: str | None = None
    summary: str | None = None
    profile: str | None = None
    website: str | None = None
    founded: int | None = None
    location: str | None = None
    aum: AumResponse | None = None
    updated_at: str | None = None

    asset_classes: list[NamedValueResponse] = Field(default_factory=list)
    strategies: list[StrategyGroupResponse] = Field(
        default_factory=list,
        description=(
            "What they allocate to, grouped: each primary strategy with the secondaries "
            "recorded under it. Prefer this over the flat lists below, which mix every asset "
            "class's strategies together."
        ),
    )
    primary_strategies: list[NamedValueResponse] = Field(default_factory=list)
    secondary_strategies: list[NamedValueResponse] = Field(default_factory=list)
    investment_regions: list[NamedValueResponse] = Field(default_factory=list)
    investment_countries: list[NamedValueResponse] = Field(default_factory=list)
    fund_structures: list[NamedValueResponse] = Field(default_factory=list)
    instruments: list[NamedValueResponse] = Field(default_factory=list)
    capital_structure_ids: list[int] = Field(
        default_factory=list,
        description="Ids only — the API returns no names for capital structures here.",
    )

    managers: list[NamedValueResponse] = Field(default_factory=list)
    consultants: list[ConsultantResponse] = Field(default_factory=list)

    contacts_total: int | None = Field(
        default=None, description="How many contacts With Intelligence holds for this investor."
    )
    contact_ids: list[int] = Field(
        default_factory=list,
        description=(
            "Every contact the investor record lists, as ids — the API returns no names here, "
            "so names, titles and seniority require a separate person lookup."
        ),
    )

    preferences_available: bool = Field(
        default=False,
        description=(
            "Whether stated allocation preferences came back. False means this subscription "
            "does not include the Intentions & Preferences add-on — NOT that the investor has "
            "stated no preferences."
        ),
    )
    preferences: dict[str, object] | None = None


class InvestorCandidateResponse(OmitNoneModel):
    id: int
    name: str | None = None
    updated_at: str | None = None


class InvestorAmbiguousResponse(OmitNoneModel):
    """Several investors matched the name. Ask which one, then call again with `investor_id`."""

    status: str = "ambiguous"
    searched_for: str
    candidates: list[InvestorCandidateResponse] = Field(default_factory=list)
    total_matches: int = 0


class InvestorNotFoundResponse(OmitNoneModel):
    """Nothing matched. The name filter may need to be closer to the investor's registered name."""

    status: str = "not_found"
    searched_for: str
    hint: str | None = None
