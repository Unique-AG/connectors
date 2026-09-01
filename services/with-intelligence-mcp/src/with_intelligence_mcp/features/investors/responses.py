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
    value: float | None = Field(default=None, description="Total assets under management.")
    as_of: str | None = Field(default=None, description="Date the figure was reported.")
    currency: str | None = None


class InvestorProfileResponse(OmitNoneModel):
    """One institutional investor, as a meeting-prep sheet.

    `managers` is who they currently allocate to. `contacts` is the key-contact subset the
    record embeds — `contacts_total` says how many exist in total. A field that is absent is
    unknown to With Intelligence, not zero.
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
    primary_strategies: list[NamedValueResponse] = Field(default_factory=list)
    secondary_strategies: list[NamedValueResponse] = Field(default_factory=list)
    investment_regions: list[NamedValueResponse] = Field(default_factory=list)
    investment_countries: list[NamedValueResponse] = Field(default_factory=list)
    fund_structures: list[NamedValueResponse] = Field(default_factory=list)
    instruments: list[NamedValueResponse] = Field(default_factory=list)
    capital_structures: list[NamedValueResponse] = Field(default_factory=list)

    managers: list[NamedValueResponse] = Field(default_factory=list)
    consultants: list[NamedValueResponse] = Field(default_factory=list)
    contacts: list[NamedValueResponse] = Field(default_factory=list)
    contacts_total: int | None = None

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
